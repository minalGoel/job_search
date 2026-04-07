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
from storage.db import JobDB
from outreach.db import OutreachDB

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
    stats = db.get_pipeline_stats()
    last_run = db.get_last_run()
    sources = db.get_source_quality_stats()
    db.close()

    odb = _outreach_db()
    outreach_stats = {
        "contacts_total": len(odb.get_all_contacts()),
        "emails_draft": len(odb.get_contacts_by_status("draft")),
        "emails_sent": len(odb.get_contacts_by_status("sent")),
        "emails_replied": len(odb.get_contacts_by_status("replied")),
    }
    # Count emails pending review (status='draft' on outreach_emails table)
    try:
        rows = odb.conn.execute(
            "SELECT COUNT(*) FROM outreach_emails WHERE status = 'draft'"
        ).fetchone()
        outreach_stats["emails_pending_review"] = rows[0] if rows else 0
        rows2 = odb.conn.execute(
            "SELECT COUNT(*) FROM outreach_emails WHERE status = 'sent'"
        ).fetchone()
        outreach_stats["emails_sent_count"] = rows2[0] if rows2 else 0
    except Exception:
        pass
    odb.conn.close()

    return {
        "jobs": stats,
        "last_run": last_run,
        "sources": sources,
        "outreach": outreach_stats,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/today")
def get_today_actions() -> dict:
    """Build the daily action queue."""
    db = _jobs_db()
    actions = []

    # New unreviewed high-priority jobs
    new_high = db.get_top_recommended_jobs(top_n=50, bucket="must_apply")
    new_high += db.get_top_recommended_jobs(top_n=50, bucket="high")
    # Filter to jobs scraped in the last 24h
    cutoff = (datetime.now().timestamp() - 86400)
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
        if a.get("status") == "applied" and a.get("applied_at"):
            try:
                age_days = (now_ts - datetime.fromisoformat(a["applied_at"]).timestamp()) / 86400
                if age_days >= 5:
                    followups.append(a)
            except Exception:
                pass
    if followups:
        actions.append({
            "type": "followup",
            "label": f"Follow up: {followups[0]['company']} application (Day {int((now_ts - datetime.fromisoformat(followups[0]['applied_at']).timestamp())/86400)})",
            "detail": f"Applied {followups[0].get('applied_at','')[:10]} · No response yet",
            "badge": "Follow-up",
            "badge_color": "amber",
            "count": len(followups),
        })

    # Interviews scheduled
    interviews = [a for a in apps if a.get("status") == "interview"]
    if interviews:
        for iv in interviews:
            actions.append({
                "type": "interview_prep",
                "label": f"Interview prep: {iv['company']}",
                "detail": iv.get("notes", "Prepare for upcoming interview"),
                "badge": "Prep",
                "badge_color": "sky",
            })

    db.close()

    # Outreach review queue
    odb = _outreach_db()
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
    odb.conn.close()

    return {"actions": actions, "date": datetime.now().strftime("%A, %b %-d")}


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
) -> dict:
    db = _jobs_db()
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

    total_row = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()
    total = total_row[0] if total_row else 0

    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    jobs = [db._row_to_dict(r) for r in rows]

    # Join with applications table for status
    app_rows = conn.execute("SELECT job_id, status, applied_at FROM applications").fetchall()
    app_status = {r[0]: {"status": r[1], "applied_at": r[2]} for r in app_rows}
    for j in jobs:
        j["application"] = app_status.get(j["id"])

    db.close()
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    db = _jobs_db()
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    matches = db.get_connection_matches_for_job(job_id)
    job["connection_matches"] = matches

    # application status
    row = db.conn.execute(
        "SELECT * FROM applications WHERE job_id = ?", (job_id,)
    ).fetchone()
    job["application"] = dict(row) if row else None
    db.close()
    return job


class ShortlistRequest(BaseModel):
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/shortlist")
def shortlist_job(job_id: str, req: ShortlistRequest = ShortlistRequest()) -> dict:
    db = _jobs_db()
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = datetime.now().isoformat()
    app_id = f"app_{job_id}"
    db.upsert_application({
        "id": app_id,
        "job_id": job_id,
        "company": job["company"],
        "title": job["title"],
        "status": "shortlisted",
        "applied_at": None,
        "last_action_at": now,
        "notes": req.notes,
    })
    db.close()
    return {"ok": True, "app_id": app_id}


class StatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/status")
def update_job_status(job_id: str, req: StatusRequest) -> dict:
    valid = {"shortlisted", "applied", "screening", "interview", "offer", "rejected", "skipped"}
    if req.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid}")

    db = _jobs_db()
    job = db.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = datetime.now().isoformat()
    app_id = f"app_{job_id}"
    db.upsert_application({
        "id": app_id,
        "job_id": job_id,
        "company": job["company"],
        "title": job["title"],
        "status": req.status,
        "applied_at": now if req.status == "applied" else None,
        "last_action_at": now,
        "notes": req.notes,
    })
    db.close()
    return {"ok": True, "status": req.status}


@app.delete("/api/jobs/{job_id}/shortlist")
def remove_shortlist(job_id: str) -> dict:
    db = _jobs_db()
    db.conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
    db.conn.commit()
    db.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATIONS / TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/applications")
def list_applications(status: str = Query("")) -> list[dict]:
    db = _jobs_db()
    apps = db.get_applications(status or None)

    # Enrich with job details
    enriched = []
    for a in apps:
        job = db.get_job_by_id(a.get("job_id", "")) if a.get("job_id") else None
        enriched.append({**a, "job": job})
    db.close()
    return enriched


@app.post("/api/applications/{app_id}/status")
def update_application_status(app_id: str, req: StatusRequest) -> dict:
    db = _jobs_db()
    now = datetime.now().isoformat()
    db.conn.execute(
        "UPDATE applications SET status = ?, last_action_at = ?, notes = COALESCE(?, notes) WHERE id = ?",
        (req.status, now, req.notes, app_id),
    )
    db.conn.commit()
    db.close()
    return {"ok": True}


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
    "weworkremotely": {"label": "WeWorkRemotely",    "icon": "🏠", "color": "slate"},
    "ycombinator":    {"label": "YCombinator",       "icon": "🚀", "color": "yellow"},
    "weekday":        {"label": "Weekday",           "icon": "📅", "color": "violet"},
}

CLOUDFLARE_PLATFORMS = {"wellfound", "glassdoor"}
LOGIN_REQUIRED = {"linkedin", "instahyre", "cutshort", "weekday"}


@app.get("/api/scrapers")
def get_scrapers() -> list[dict]:
    db = _jobs_db()

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
    contacts = odb.get_all_contacts()
    odb.conn.close()
    return contacts


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
        result = [dict(r) for r in rows]
    except Exception:
        result = []
    odb.conn.close()
    return result


@app.get("/api/outreach/stats")
def outreach_stats() -> dict:
    odb = _outreach_db()
    stats: dict[str, Any] = {}
    try:
        for s in ("new", "enriched", "draft", "approved", "sent", "replied", "skipped"):
            stats[s] = odb.conn.execute(
                "SELECT COUNT(*) FROM outreach_contacts WHERE status = ?", (s,)
            ).fetchone()[0]
        for es in ("draft", "approved", "sent"):
            stats[f"emails_{es}"] = odb.conn.execute(
                "SELECT COUNT(*) FROM outreach_emails WHERE status = ?", (es,)
            ).fetchone()[0]
        credits = odb.conn.execute(
            "SELECT provider, SUM(credits_used) FROM outreach_credits GROUP BY provider"
        ).fetchall()
        stats["credits_used"] = {r[0]: r[1] for r in credits}
    except Exception:
        pass
    odb.conn.close()
    return stats


class EmailEditRequest(BaseModel):
    subject: str
    body_plain: str
    body_html: Optional[str] = None


@app.post("/api/outreach/emails/{email_id}/approve")
def approve_email(email_id: str) -> dict:
    odb = _outreach_db()
    odb.update_email_status(email_id, "approved")
    odb.conn.close()
    return {"ok": True}


@app.post("/api/outreach/emails/{email_id}/skip")
def skip_email(email_id: str) -> dict:
    odb = _outreach_db()
    odb.update_email_status(email_id, "skipped")
    odb.conn.close()
    return {"ok": True}


@app.post("/api/outreach/emails/{email_id}/edit")
def edit_email(email_id: str, req: EmailEditRequest) -> dict:
    odb = _outreach_db()
    body_html = req.body_html or req.body_plain.replace("\n", "<br>")
    odb.update_email_content(email_id, req.subject, req.body_plain, body_html)
    odb.conn.close()
    return {"ok": True}


@app.post("/api/outreach/contacts/{contact_id}/skip")
def skip_contact(contact_id: str) -> dict:
    odb = _outreach_db()
    odb.update_contact_status(contact_id, "skipped")
    odb.conn.close()
    return {"ok": True}


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
    conn = db.conn

    # VC portal jobs are stored with platform starting with "vc_" or specific known names
    total_row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE is_duplicate = 0 AND (platform LIKE 'vc_%' OR platform = 'vc_portals')"
    ).fetchone()
    total = total_row[0] if total_row else 0

    offset = (page - 1) * limit
    rows = conn.execute(
        """SELECT * FROM jobs WHERE is_duplicate = 0 AND (platform LIKE 'vc_%' OR platform = 'vc_portals')
           ORDER BY scraped_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    jobs = [db._row_to_dict(r) for r in rows]
    db.close()
    return {"jobs": jobs, "total": total}


@app.get("/api/vc-registry")
def get_vc_registry() -> list[dict]:
    """Return the VC portal registry metadata."""
    try:
        from vc_portals.registry import VC_PORTALS
        return [
            {
                "name": v.name,
                "job_portal_url": v.job_portal_url,
                "job_portal_type": getattr(v, "job_portal_type", "custom"),
                "location": v.location,
                "stage_focus": v.stage_focus,
                "notes": v.notes,
            }
            for v in VC_PORTALS
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


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
    odb.conn.close()

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
    db.close()
    return result


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
    return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# DRAFT MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs/{job_id}/draft")
def get_draft(job_id: str, type: str = Query("recruiter"), mutual: str = Query("")) -> dict:
    """Return a draft outreach message for a job."""
    try:
        from services.outreach_writer import OutreachWriter
        writer = OutreachWriter()
        db = _jobs_db()
        job = db.get_job_by_id(job_id)
        db.close()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        msg = writer.draft(
            job=job,
            message_type=type,
            mutual_connection=mutual or None,
        )
        return {"draft": msg, "job_id": job_id, "type": type}
    except Exception as exc:
        return {"draft": f"[Draft unavailable: {exc}]", "job_id": job_id, "type": type}


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
