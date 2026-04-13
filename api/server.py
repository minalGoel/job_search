"""
api/server.py — FastAPI backend for the PM Job Search dashboard.

Serves:
  - REST API at /api/...   (reads live from jobs.db / outreach.db)
  - WebSocket at /ws/scrape (streams subprocess stdout)
  - Static SPA at /        (static/index.html)
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Make sure project root is importable ──────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Local imports ─────────────────────────────────────────────────────────────
from storage.db import (
    JobDB,
    APPLICATION_STATUSES,
    STATUSES_COUNTING_AS_APPLIED,
    application_id_for,
)
from outreach.db import OutreachDB
from services.location_filter import is_acceptable_location

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="PMHunt Dashboard", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIES_DIR = ROOT / "cookies"
OUTPUT_DIR = ROOT / "output"
PYTHON = str(ROOT / ".venv" / "bin" / "python")
MAIN_PY = str(ROOT / "main.py")

# ── DB helpers ────────────────────────────────────────────────────────────────

def _jobs_db() -> JobDB:
    return JobDB(OUTPUT_DIR / "jobs.db")


def _outreach_db() -> OutreachDB:
    return OutreachDB(OUTPUT_DIR / "outreach.db")


# ── Subprocess helper ─────────────────────────────────────────────────────────

async def _run_cmd_stream(args: list[str], ws: WebSocket) -> int:
    """Run a CLI command, streaming stdout/stderr lines to a WebSocket."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(ROOT),
    )
    assert proc.stdout
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        await ws.send_json({"type": "log", "line": line})
    await proc.wait()
    return proc.returncode or 0


async def _run_cmd_bg(args: list[str]) -> tuple[int, str]:
    """Run a CLI command to completion, return (returncode, combined output)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(ROOT),
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD / STATS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
def get_stats() -> dict:
    db = _jobs_db()
    odb = _outreach_db()
    try:
        stats = db.get_pipeline_stats()
        last_run = db.get_last_run()
        sources = db.get_source_quality_stats()

        outreach_stats = {
            "contacts_total": len(odb.get_all_contacts()),
            "contacts_replied": len(odb.get_contacts_by_status("replied")),
        }
        try:
            for email_status in ("draft", "approved", "sent", "bounced"):
                row = odb.conn.execute(
                    "SELECT COUNT(*) FROM outreach_emails WHERE status = ?",
                    (email_status,),
                ).fetchone()
                outreach_stats[f"emails_{email_status}"] = row[0] if row else 0
        except Exception:
            pass

        return {
            "jobs": stats,
            "last_run": last_run,
            "sources": sources,
            "outreach": outreach_stats,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        db.close()
        try:
            odb.conn.close()
        except Exception:
            pass


@app.get("/api/today")
def get_today_actions() -> dict:
    """Build the daily action queue."""
    db = _jobs_db()
    odb = _outreach_db()
    actions: list[dict] = []
    try:
        # New unreviewed high-priority jobs
        new_high = db.get_top_recommended_jobs(top_n=50, bucket="must_apply")
        new_high += db.get_top_recommended_jobs(top_n=50, bucket="high")

        # Filter to jobs scraped in the last 24h
        cutoff = datetime.now().timestamp() - 86400
        recent_high = []
        for j in new_high:
            try:
                t = datetime.fromisoformat(j["scraped_at"]).timestamp()
                if t > cutoff:
                    recent_high.append(j)
            except Exception:
                pass

        if recent_high:
            companies = list({j["company"] for j in recent_high[:5]})
            actions.append({
                "type": "review_jobs",
                "label": f"Review {len(recent_high)} new high-priority jobs",
                "detail": ", ".join(companies[:4]) + (f" + {len(companies)-4} more" if len(companies) > 4 else ""),
                "badge": "Apply",
                "badge_color": "brand",
                "count": len(recent_high),
            })

        # Applications needing follow-up (applied > 5 days ago, no status change)
        apps = db.get_applications()
        now_ts = datetime.now().timestamp()
        followups = []
        for a in apps:
            if a.get("status") in STATUSES_COUNTING_AS_APPLIED and a.get("applied_at"):
                try:
                    age_days = (now_ts - datetime.fromisoformat(a["applied_at"]).timestamp()) / 86400
                    if age_days >= 5:
                        followups.append(a)
                except Exception:
                    pass
        if followups:
            first = followups[0]
            age = int((now_ts - datetime.fromisoformat(first["applied_at"]).timestamp()) / 86400)
            actions.append({
                "type": "followup",
                "label": f"Follow up: {first['company']} application (Day {age})",
                "detail": f"Applied {first.get('applied_at','')[:10]} · No response yet",
                "badge": "Follow-up",
                "badge_color": "amber",
                "count": len(followups),
            })

        # Interviews scheduled
        interviews = [a for a in apps if a.get("status") == "interview"]
        for iv in interviews:
            actions.append({
                "type": "interview_prep",
                "label": f"Interview prep: {iv['company']}",
                "detail": iv.get("notes", "Prepare for upcoming interview"),
                "badge": "Prep",
                "badge_color": "sky",
            })

        # Outreach review queue
        try:
            pending_emails = odb.conn.execute(
                """SELECT e.id, c.company, c.contact_name
                   FROM outreach_emails e
                   JOIN outreach_contacts c ON c.id = e.contact_id
                   WHERE e.status = 'draft' LIMIT 10"""
            ).fetchall()
            if pending_emails:
                companies = list({r[1] for r in pending_emails[:3]})
                actions.append({
                    "type": "outreach_review",
                    "label": f"{len(pending_emails)} outreach emails ready to review",
                    "detail": "Recruiters at " + ", ".join(companies),
                    "badge": "Review",
                    "badge_color": "green",
                    "count": len(pending_emails),
                })
        except Exception:
            pass

        return {"actions": actions, "date": datetime.now().strftime("%A, %b %-d")}
    finally:
        db.close()
        try:
            odb.conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# JOBS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs")
def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    platform: str = Query(""),
    bucket: str = Query(""),
    search: str = Query(""),
    sort: str = Query("relevance"),
    include_duplicates: bool = Query(False),
    location_mode: str = Query("strict", pattern="^(strict|all)$",
                               description="strict = only NCR + global remote; all = include mislocated legacy rows"),
) -> dict:
    db = _jobs_db()
    try:
        conn = db.conn

        conditions = []
        params: list[Any] = []

        if not include_duplicates:
            conditions.append("is_duplicate = 0")

        if platform:
            conditions.append("platform = ?")
            params.append(platform)

        if bucket:
            conditions.append("priority_bucket = ?")
            params.append(bucket)

        if search:
            conditions.append("(LOWER(title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(description) LIKE ?)")
            like = f"%{search.lower()}%"
            params += [like, like, like]

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        sort_map = {
            "relevance": "priority_score DESC, scraped_at DESC",
            "date": "scraped_at DESC",
            "salary": "salary DESC NULLS LAST, scraped_at DESC",
            "company": "company ASC",
        }
        order = sort_map.get(sort, "priority_score DESC, scraped_at DESC")

        # NOTE: location filtering happens post-SQL in Python because the
        # rules (regional restrictions, country codes, etc.) are too rich for
        # a LIKE clause. We over-fetch when strict mode is on, then trim.
        if location_mode == "strict":
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY {order}",
                params,
            ).fetchall()
            all_jobs = [db._row_to_dict(r) for r in rows]
            filtered = [j for j in all_jobs if is_acceptable_location(j.get("location", ""))]
            total = len(filtered)
            offset = (page - 1) * limit
            jobs = filtered[offset:offset + limit]
        else:
            total_row = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()
            total = total_row[0] if total_row else 0
            offset = (page - 1) * limit
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            jobs = [db._row_to_dict(r) for r in rows]

        # Join with applications table for status.
        # Ordering by last_action_at DESC and taking the first row per job_id
        # guarantees determinism even if legacy duplicate application rows
        # exist for the same job (from before the shared application_id_for
        # helper landed).
        app_rows = conn.execute(
            "SELECT job_id, status, applied_at, last_action_at FROM applications "
            "ORDER BY COALESCE(last_action_at, '') DESC"
        ).fetchall()
        app_status: dict[str, dict] = {}
        for r in app_rows:
            if r[0] and r[0] not in app_status:
                app_status[r[0]] = {"status": r[1], "applied_at": r[2]}
        for j in jobs:
            j["application"] = app_status.get(j["id"])

        return {
            "jobs": jobs,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
        }
    finally:
        db.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    db = _jobs_db()
    try:
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        matches = db.get_connection_matches_for_job(job_id)
        job["connection_matches"] = matches

        # application status
        row = db.conn.execute(
            "SELECT * FROM applications WHERE job_id = ? ORDER BY COALESCE(last_action_at, '') DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        job["application"] = dict(row) if row else None
        return job
    finally:
        db.close()


class ShortlistRequest(BaseModel):
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/shortlist")
def shortlist_job(job_id: str, req: ShortlistRequest = ShortlistRequest()) -> dict:
    db = _jobs_db()
    try:
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        now = datetime.now().isoformat()
        app_id = application_id_for(job_id)
        db.upsert_application({
            "id": app_id,
            "job_id": job_id,
            "company": job["company"],
            "title": job["title"],
            "status": "shortlisted",
            "applied_at": None,  # COALESCE in upsert preserves existing value
            "last_action_at": now,
            "notes": req.notes,
        })
        return {"ok": True, "app_id": app_id}
    finally:
        db.close()


class StatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/status")
def update_job_status(job_id: str, req: StatusRequest) -> dict:
    if req.status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(APPLICATION_STATUSES)}",
        )

    db = _jobs_db()
    try:
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        now = datetime.now().isoformat()
        app_id = application_id_for(job_id)
        # Only set applied_at when entering a status that counts as applied,
        # AND only if the row doesn't already have one (upsert's COALESCE
        # handles the "already set" case).
        new_applied_at = now if req.status in STATUSES_COUNTING_AS_APPLIED else None
        db.upsert_application({
            "id": app_id,
            "job_id": job_id,
            "company": job["company"],
            "title": job["title"],
            "status": req.status,
            "applied_at": new_applied_at,
            "last_action_at": now,
            "notes": req.notes,
        })
        return {"ok": True, "status": req.status}
    finally:
        db.close()


@app.delete("/api/jobs/{job_id}/shortlist")
def remove_shortlist(job_id: str) -> dict:
    db = _jobs_db()
    try:
        db.conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATIONS / TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/applications")
def list_applications(status: str = Query("")) -> list[dict]:
    if status and status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status filter. Must be one of: {sorted(APPLICATION_STATUSES)}",
        )
    db = _jobs_db()
    try:
        apps = db.get_applications(status or None)
        # Enrich with job details
        enriched = []
        for a in apps:
            job = db.get_job_by_id(a.get("job_id", "")) if a.get("job_id") else None
            enriched.append({**a, "job": job})
        return enriched
    finally:
        db.close()


@app.post("/api/applications/{app_id}/status")
def update_application_status(app_id: str, req: StatusRequest) -> dict:
    if req.status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(APPLICATION_STATUSES)}",
        )
    db = _jobs_db()
    try:
        now = datetime.now().isoformat()
        # Only stamp applied_at if entering an "applied" state AND we don't
        # already have one (COALESCE via the UPDATE below).
        set_applied = req.status in STATUSES_COUNTING_AS_APPLIED
        if set_applied:
            db.conn.execute(
                """UPDATE applications
                   SET status = ?,
                       last_action_at = ?,
                       applied_at = COALESCE(applied_at, ?),
                       notes = COALESCE(?, notes)
                   WHERE id = ?""",
                (req.status, now, now, req.notes, app_id),
            )
        else:
            db.conn.execute(
                """UPDATE applications
                   SET status = ?, last_action_at = ?, notes = COALESCE(?, notes)
                   WHERE id = ?""",
                (req.status, now, req.notes, app_id),
            )
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPERS
# ═══════════════════════════════════════════════════════════════════════════════

PLATFORM_META: dict[str, dict] = {
    "naukri":         {"label": "Naukri",           "icon": "📋", "color": "blue"},
    "linkedin":       {"label": "LinkedIn",          "icon": "🔗", "color": "orange"},
    "iimjobs":        {"label": "IIMJobs",           "icon": "💼", "color": "green"},
    "wellfound":      {"label": "Wellfound",         "icon": "🌿", "color": "purple"},
    "cutshort":       {"label": "Cutshort",          "icon": "✂️", "color": "indigo"},
    "instahyre":      {"label": "Instahyre",         "icon": "📡", "color": "sky"},
    "foundit":        {"label": "Foundit",           "icon": "🔍", "color": "pink"},
    "indeed":         {"label": "Indeed",            "icon": "🌐", "color": "blue"},
    "glassdoor":      {"label": "Glassdoor",         "icon": "🪟", "color": "teal"},
    "hirist":         {"label": "Hirist",            "icon": "👨‍💻", "color": "cyan"},
    "remoteok":       {"label": "RemoteOK",          "icon": "🌍", "color": "green"},
    "ycombinator":    {"label": "YCombinator",       "icon": "🚀", "color": "yellow"},
    "weekday":        {"label": "Weekday",           "icon": "📅", "color": "violet"},
}

CLOUDFLARE_PLATFORMS = {"wellfound", "glassdoor"}
LOGIN_REQUIRED = {"linkedin", "instahyre", "cutshort", "weekday"}


@app.get("/api/scrapers")
def get_scrapers() -> list[dict]:
    db = _jobs_db()
    try:
        # Per-platform job counts
        counts = {
            r[0]: r[1]
            for r in db.conn.execute(
                "SELECT platform, COUNT(*) FROM jobs WHERE is_duplicate = 0 GROUP BY platform"
            ).fetchall()
        }

        # Last scrape per platform (from jobs table)
        last_scraped = {
            r[0]: r[1]
            for r in db.conn.execute(
                "SELECT platform, MAX(scraped_at) FROM jobs GROUP BY platform"
            ).fetchall()
        }
    finally:
        db.close()

    # Cookie health
    cookie_health: dict[str, str] = {}
    if COOKIES_DIR.exists():
        for f in COOKIES_DIR.glob("*.json"):
            name = f.stem
            try:
                data = json.loads(f.read_text())
                cookies = data.get("cookies", [])
                # Check if any session cookie exists and is not expired
                now_ms = datetime.now().timestamp() * 1000
                valid = any(
                    c.get("expires", 0) * 1000 > now_ms or c.get("expires", -1) == -1
                    for c in cookies if "session" in c.get("name", "").lower()
                )
                cookie_health[name] = "active" if (cookies and valid) else "expired"
            except Exception:
                cookie_health[name] = "missing"

    result = []
    from scrapers import SCRAPER_REGISTRY
    for name in SCRAPER_REGISTRY:
        meta = PLATFORM_META.get(name, {"label": name.title(), "icon": "🔲", "color": "slate"})
        last = last_scraped.get(name)
        health = "ok"
        health_msg = ""
        if name in CLOUDFLARE_PLATFORMS:
            health = "blocked"
            health_msg = "Cloudflare blocked"
        elif name in LOGIN_REQUIRED:
            c = cookie_health.get(name, "missing")
            if c == "active":
                health = "ok"
            elif c == "expired":
                health = "warning"
                health_msg = "Session expired — re-login needed"
            else:
                health = "warning"
                health_msg = "No session cookie — login required"

        result.append({
            "name": name,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "job_count": counts.get(name, 0),
            "last_scraped": last,
            "health": health,
            "health_msg": health_msg,
            "requires_login": name in LOGIN_REQUIRED,
            "cloudflare": name in CLOUDFLARE_PLATFORMS,
        })

    return result


# ── WebSocket scrape runner ────────────────────────────────────────────────────

@app.websocket("/ws/scrape")
async def ws_scrape(ws: WebSocket, platforms: str = Query("")):
    await ws.accept()
    try:
        args = [PYTHON, MAIN_PY]
        if platforms:
            # -p naukri -p linkedin …
            for p in platforms.split(","):
                p = p.strip()
                if p:
                    args += ["-p", p]
            args = [PYTHON, MAIN_PY, "run"] + args[2:]
        else:
            args.append("run")

        await ws.send_json({"type": "start", "cmd": " ".join(args)})
        rc = await _run_cmd_stream(args, ws)
        await ws.send_json({"type": "done", "returncode": rc})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await ws.send_json({"type": "error", "msg": str(exc)})


@app.websocket("/ws/command")
async def ws_command(ws: WebSocket, cmd: str = Query(...)):
    """Generic command runner for vc-jobs, funding, outreach-enrich, etc."""
    await ws.accept()
    try:
        # Whitelist of safe commands
        allowed = {
            "vc-jobs", "mnc-jobs", "funding", "run-all",
            "recommend", "outreach-enrich", "outreach-send",
            "company-intel-refresh",
        }
        if cmd not in allowed:
            await ws.send_json({"type": "error", "msg": f"Command '{cmd}' not allowed"})
            return
        args = [PYTHON, MAIN_PY, cmd]
        await ws.send_json({"type": "start", "cmd": cmd})
        rc = await _run_cmd_stream(args, ws)
        await ws.send_json({"type": "done", "returncode": rc})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await ws.send_json({"type": "error", "msg": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════════
# OUTREACH
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/outreach/contacts")
def list_contacts() -> list[dict]:
    odb = _outreach_db()
    try:
        return odb.get_all_contacts()
    finally:
        odb.close()


@app.get("/api/outreach/emails")
def list_emails(status: str = Query("")) -> list[dict]:
    odb = _outreach_db()
    try:
        if status:
            rows = odb.conn.execute(
                """SELECT e.*, c.company, c.contact_name, c.contact_email,
                          c.contact_title, c.source_job_title, c.contact_email_status
                   FROM outreach_emails e
                   JOIN outreach_contacts c ON c.id = e.contact_id
                   WHERE e.status = ? ORDER BY e.scheduled_send_at DESC""",
                (status,),
            ).fetchall()
        else:
            rows = odb.conn.execute(
                """SELECT e.*, c.company, c.contact_name, c.contact_email,
                          c.contact_title, c.source_job_title, c.contact_email_status
                   FROM outreach_emails e
                   JOIN outreach_contacts c ON c.id = e.contact_id
                   ORDER BY e.scheduled_send_at DESC""",
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        odb.close()


@app.get("/api/outreach/stats")
def outreach_stats() -> dict:
    odb = _outreach_db()
    stats: dict[str, Any] = {}
    try:
        for s in ("new", "enriched", "draft", "approved", "sent", "replied", "skipped"):
            stats[f"contacts_{s}"] = odb.conn.execute(
                "SELECT COUNT(*) FROM outreach_contacts WHERE status = ?", (s,)
            ).fetchone()[0]
        for es in ("draft", "approved", "sent", "bounced"):
            stats[f"emails_{es}"] = odb.conn.execute(
                "SELECT COUNT(*) FROM outreach_emails WHERE status = ?", (es,)
            ).fetchone()[0]
        credits = odb.conn.execute(
            "SELECT provider, SUM(credits_used) FROM outreach_credits GROUP BY provider"
        ).fetchall()
        stats["credits_used"] = {r[0]: r[1] for r in credits}
    except Exception:
        pass
    finally:
        odb.close()
    return stats


class EmailEditRequest(BaseModel):
    subject: str
    body_plain: str
    body_html: Optional[str] = None


@app.post("/api/outreach/emails/{email_id}/approve")
def approve_email(email_id: str) -> dict:
    odb = _outreach_db()
    try:
        odb.update_email_status(email_id, "approved")
        return {"ok": True}
    finally:
        odb.close()


@app.post("/api/outreach/emails/{email_id}/skip")
def skip_email(email_id: str) -> dict:
    odb = _outreach_db()
    try:
        odb.update_email_status(email_id, "skipped")
        # Sync contact terminal status (mirrors reviewer.py behaviour)
        contact_id = odb.get_contact_id_for_email(email_id)
        if contact_id and odb.all_emails_terminal_for_contact(contact_id):
            odb.update_contact_status(contact_id, "skipped")
        return {"ok": True}
    finally:
        odb.close()


@app.post("/api/outreach/emails/{email_id}/edit")
def edit_email(email_id: str, req: EmailEditRequest) -> dict:
    odb = _outreach_db()
    try:
        body_html = req.body_html or req.body_plain.replace("\n", "<br>")
        odb.update_email_content(email_id, req.subject, req.body_plain, body_html)
        return {"ok": True}
    finally:
        odb.close()


@app.post("/api/outreach/contacts/{contact_id}/skip")
def skip_contact(contact_id: str) -> dict:
    odb = _outreach_db()
    try:
        odb.update_contact_status(contact_id, "skipped")
        # Cancel all pending/approved emails for this contact so none are sent
        odb.cancel_all_pending_emails(contact_id)
        return {"ok": True}
    finally:
        odb.close()


# ═══════════════════════════════════════════════════════════════════════════════
# FUNDING
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/funding")
def get_funding() -> list[dict]:
    """Read the latest funded_companies CSV from output/."""
    csvs = sorted(OUTPUT_DIR.glob("funded_companies_*.csv"), reverse=True)
    if not csvs:
        # Try the non-dated one
        f = OUTPUT_DIR / "funded_companies.csv"
        if not f.exists():
            return []
        csvs = [f]
    latest = csvs[0]
    results = []
    try:
        with open(latest, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                results.append(row)
    except Exception:
        pass
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VC PORTALS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/vc-jobs")
def get_vc_jobs(page: int = 1, limit: int = 50) -> dict:
    """Return jobs from platforms prefixed 'vc_' or scraped by VC portal scraper."""
    db = _jobs_db()
    try:
        conn = db.conn
        # Fetch all VC jobs (no LIMIT here — we need to filter first, then paginate)
        rows = conn.execute(
            """SELECT * FROM jobs WHERE is_duplicate = 0 AND (platform LIKE 'vc_%' OR platform = 'vc_portals')
               ORDER BY scraped_at DESC""",
        ).fetchall()
        all_jobs = [db._row_to_dict(r) for r in rows]
        # Apply location filter — total must reflect the filtered set for correct pagination
        filtered = [j for j in all_jobs if is_acceptable_location(j.get("location", ""))]
        total = len(filtered)
        offset = (page - 1) * limit
        jobs = filtered[offset:offset + limit]
        return {"jobs": jobs, "total": total}
    finally:
        db.close()


@app.get("/api/vc-registry")
def get_vc_registry() -> list[dict]:
    """Return the VC portal registry metadata."""
    try:
        from vc_portals.registry import VC_REGISTRY
        return [
            {
                "name": v.name,
                "job_portal_url": v.job_portal_url,
                "job_portal_type": getattr(v, "job_portal_type", "custom"),
            }
            for v in VC_REGISTRY
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


# ═══════════════════════════════════════════════════════════════════════════════
# YC STARTUPS
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/api/yc/stats")
def get_yc_stats() -> dict:
    db = _jobs_db()
    try:
        return db.get_yc_stats()
    finally:
        db.close()


@app.get("/api/yc/batches")
def get_yc_batches() -> list[str]:
    db = _jobs_db()
    try:
        return db.get_yc_batches()
    finally:
        db.close()


@app.get("/api/yc/companies")
def list_yc_companies(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    batch: str = Query(""),
    hiring_only: bool = Query(False),
    hiring_pm_only: bool = Query(False),
    indian_founders_only: bool = Query(False),
    locations: str = Query(""),   # comma-separated exact hq_location values
    industries: str = Query(""),  # comma-separated exact industry values
    team_size_min: int = Query(0, ge=0),
    search: str = Query(""),
) -> dict:
    db = _jobs_db()
    try:
        loc_list = [v.strip() for v in locations.split(",") if v.strip()] if locations else None
        ind_list = [v.strip() for v in industries.split(",") if v.strip()] if industries else None
        total = db.count_yc_companies(
            batch=batch, hiring_only=hiring_only, hiring_pm_only=hiring_pm_only,
            indian_founders_only=indian_founders_only, locations=loc_list,
            industries=ind_list, team_size_min=team_size_min, search=search,
        )
        offset = (page - 1) * limit
        companies = db.get_yc_companies(
            batch=batch, hiring_only=hiring_only, hiring_pm_only=hiring_pm_only,
            indian_founders_only=indian_founders_only, locations=loc_list,
            industries=ind_list, team_size_min=team_size_min, search=search,
            limit=limit, offset=offset,
        )
        return {
            "companies": companies,
            "total": total,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
        }
    finally:
        db.close()


@app.get("/api/yc/locations")
def get_yc_locations() -> list[str]:
    """Distinct hq_location values for the location multi-select filter."""
    db = _jobs_db()
    try:
        return db.get_yc_locations()
    finally:
        db.close()


@app.get("/api/yc/industries")
def get_yc_industries() -> list[str]:
    """Distinct industry values for the industry multi-select filter."""
    db = _jobs_db()
    try:
        return db.get_yc_industries()
    finally:
        db.close()


@app.get("/api/yc/companies/{company_id}")
def get_yc_company(company_id: str) -> dict:
    db = _jobs_db()
    try:
        company = db.get_yc_company_by_id(company_id)
        if not company:
            raise HTTPException(404, "YC company not found")
        signals = db.get_yc_hiring_signals(company_id)
        founders = db.get_yc_founder_contacts(company_id)
        return {"company": company, "signals": signals, "founders": founders}
    finally:
        db.close()


@app.get("/api/yc/founders")
def list_yc_founders() -> list[dict]:
    db = _jobs_db()
    try:
        return db.get_yc_all_founder_contacts()
    finally:
        db.close()


@app.post("/api/yc/sync")
async def trigger_yc_sync(batch: Optional[str] = Query(None)) -> dict:
    """Trigger YC sync as a background subprocess."""
    args = [PYTHON, MAIN_PY, "yc-sync"]
    if batch:
        args.extend(["--batch", batch])
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(ROOT),
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace") if stdout else ""
    return {"status": "ok" if proc.returncode == 0 else "error", "output": output[-1000:]}


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/analytics")
def get_analytics() -> dict:
    db = _jobs_db()
    sources = db.get_source_quality_stats()
    stats = db.get_pipeline_stats()
    apps = db.get_applications()
    db.close()

    funnel = {
        "scraped": stats.get("total_jobs", 0),
        "scored": stats.get("scored_jobs", 0),
        "must_apply": stats.get("bucket_must_apply", 0),
        "high": stats.get("bucket_high", 0),
        "shortlisted": stats.get("applications_by_status", {}).get("shortlisted", 0),
        "applied": stats.get("applications_by_status", {}).get("applied", 0),
        "screening": stats.get("applications_by_status", {}).get("screening", 0),
        "interview": stats.get("applications_by_status", {}).get("interview", 0),
        "offer": stats.get("applications_by_status", {}).get("offer", 0),
    }

    odb = _outreach_db()
    outreach = {}
    try:
        sent = odb.conn.execute(
            "SELECT COUNT(*) FROM outreach_emails WHERE status = 'sent'"
        ).fetchone()[0]
        replied = odb.conn.execute(
            "SELECT COUNT(*) FROM outreach_contacts WHERE status = 'replied'"
        ).fetchone()[0]
        outreach = {"sent": sent, "replied": replied, "reply_rate": round(replied / sent * 100, 1) if sent else 0}
    except Exception:
        pass
    finally:
        odb.close()

    # Cookie health
    cookie_statuses: dict[str, str] = {}
    if COOKIES_DIR.exists():
        for f in COOKIES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                cookies = data.get("cookies", [])
                now_ms = datetime.now().timestamp() * 1000
                valid = any(
                    c.get("expires", 0) * 1000 > now_ms or c.get("expires", -1) == -1
                    for c in cookies if "session" in c.get("name", "").lower()
                )
                cookie_statuses[f.stem] = "active" if (cookies and valid) else "expired"
            except Exception:
                cookie_statuses[f.stem] = "missing"

    for p in CLOUDFLARE_PLATFORMS:
        cookie_statuses[p] = "cloudflare"

    return {
        "sources": sources,
        "funnel": funnel,
        "outreach": outreach,
        "cookies": cookie_statuses,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RUNS HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/runs")
def get_runs(limit: int = 10) -> list[dict]:
    db = _jobs_db()
    try:
        rows = db.conn.execute(
            "SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["platforms_scraped"] = json.loads(d.get("platforms_scraped") or "[]")
            except Exception:
                d["platforms_scraped"] = []
            try:
                d["errors"] = json.loads(d.get("errors") or "{}")
            except Exception:
                d["errors"] = {}
            result.append(d)
        return result
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/recommendations")
def get_recommendations(
    top: int = Query(25, ge=1, le=200),
    bucket: str = Query(""),
    platform: str = Query(""),
    remote_only: bool = Query(False),
) -> list[dict]:
    db = _jobs_db()
    jobs = db.get_top_recommended_jobs(
        top_n=top,
        bucket=bucket or None,
        platform=platform or None,
        remote_only=remote_only,
    )
    db.close()
    return [j for j in jobs if is_acceptable_location(j.get("location", ""))]


# ═══════════════════════════════════════════════════════════════════════════════
# DRAFT MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs/{job_id}/draft")
def get_draft(job_id: str, type: str = Query("recruiter"), mutual: str = Query("")) -> dict:
    """Return a draft outreach message for a job."""
    db = _jobs_db()
    try:
        from services.outreach_writer import draft_message
        job = db.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        msg = draft_message(
            job=job,
            message_type=type,
            mutual_name=mutual or "",
        )
        return {"draft": msg, "job_id": job_id, "type": type}
    except HTTPException:
        raise
    except Exception as exc:
        return {"draft": f"[Draft unavailable: {exc}]", "job_id": job_id, "type": type}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC FILES + SPA
# ═══════════════════════════════════════════════════════════════════════════════

STATIC_DIR = ROOT / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_spa():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Frontend not built yet. Run: python main.py serve"})
