"""One enrichment pass over stored jobs: structured detail → local LLM → resolved location.

    enrich_jobs(db, ...) → EnrichStats

Order per job: (1) fetch the structured detail record for the posting URL
(services.job_detail) unless we already have a good one; (2) if that leaves the city
open and there is real text, ask the local LLM (services.llm_extractor); (3) resolve
(services.location_resolver) and upsert the job_enrichment row; (4) when the verdict or
work mode changed, clear ``priority_bucket`` so the existing "unscored" sentinel makes
the scorer revisit the job. Runs after every scrape for that run's inserted ids and as
``python main.py enrich [--backfill]``. Never raises for one job; never deletes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx
import structlog

from config.settings import Settings
from services.job_detail import DetailLocation, DetailRecord, fetch_detail, strategy_for
from services.llm_extractor import LLMResult, OllamaExtractor, is_placeholder_description
from services.location_resolver import resolve
from storage.db import JobDB

log = structlog.get_logger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BLOCKED_RETRY_DAYS = 7


@dataclass
class EnrichStats:
    considered: int = 0
    detail_fetched: int = 0
    detail_ok: int = 0
    detail_blocked: int = 0
    detail_reused: int = 0
    llm_called: int = 0
    llm_ok: int = 0
    llm_skipped_reason: dict[str, int] = field(default_factory=dict)
    resolved_structured: int = 0
    resolved_llm: int = 0
    resolved_listing: int = 0
    hidden: int = 0          # location_ok == 0 after this pass
    changed: int = 0         # verdict/work-mode flipped vs the previous row
    rescored: int = 0        # priority_bucket cleared for the scorer
    duration_s: float = 0.0
    llm_status: str = ""     # preflight outcome

    def as_dict(self) -> dict:
        return asdict(self)


def _detail_from_row(row: dict) -> Optional[DetailRecord]:
    """Rebuild a DetailRecord from a stored job_enrichment row (for reuse / re-resolution)."""
    if not row or not row.get("en_detail_status"):
        return None
    try:
        locs = json.loads(row.get("en_locations_json") or "[]")
    except ValueError:
        locs = []
    rec = DetailRecord(source=row.get("en_detail_source") or "", status=row.get("en_detail_status") or "none",
                       url=row.get("en_detail_url") or "", workplace_type=row.get("en_workplace_type") or "",
                       description=row.get("en_description_full") or "", posted_date=row.get("en_posted_date") or "",
                       employment_type=row.get("en_employment_type") or "")
    rec.locations = [DetailLocation(**{k: (l.get(k) or "") for k in ("city", "region", "country", "postal", "raw")}) for l in locs if isinstance(l, dict)]
    return rec


def _should_refetch(row: Optional[dict]) -> bool:
    if not row or not row.get("en_detail_status"):
        return True
    status = row["en_detail_status"]
    if status == "ok":
        return False
    fetched_at = row.get("en_detail_fetched_at") or ""
    if status == "blocked" and fetched_at:
        try:
            return datetime.fromisoformat(fetched_at) < datetime.now() - timedelta(days=BLOCKED_RETRY_DAYS)
        except ValueError:
            return True
    return True  # 'none' / 'error' → try again (parsers improve, sites change)


def _llm_needed(job: dict, detail: Optional[DetailRecord]) -> tuple[bool, str]:
    if detail is not None and detail.status == "ok" and detail.city_level():
        return False, "structured_has_city"
    if detail is not None and detail.status == "blocked":
        return False, "detail_blocked"
    text = (detail.description if detail and detail.description else job.get("description") or "")
    if is_placeholder_description(text):
        return False, "no_text"
    return True, ""


def _llm_row(res: Optional[LLMResult], model: str) -> dict:
    if res is None:
        return {"en_llm_status": "skipped", "en_llm_model": model}
    data = res.data or {}
    return {
        "en_llm_status": res.status,
        "en_llm_model": res.model or model,
        "en_llm_json": json.dumps({**data, "dropped": res.dropped, "latency_ms": res.latency_ms}, ensure_ascii=False),
        "en_seniority": data.get("seniority") or "",
        "en_role_type": data.get("role_type") or "",
        "en_years_min": data.get("years_min"),
        "en_years_max": data.get("years_max"),
    }


async def _fetch_details(jobs: list[dict], previous: dict[str, dict], settings: Settings, stats: EnrichStats, log_: Any) -> dict[str, DetailRecord]:
    """Structured layer for every job that needs it, concurrently, per-host throttled."""
    todo = [j for j in jobs if strategy_for(j.get("apply_link") or "") != "none" and _should_refetch(previous.get(j["id"]))]
    out: dict[str, DetailRecord] = {}
    if not todo:
        return out
    host_sems: dict[str, asyncio.Semaphore] = {}
    sem = asyncio.Semaphore(8)
    limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
    async with httpx.AsyncClient(headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"}, follow_redirects=True,
                                 timeout=settings.MNC_HTTP_TIMEOUT, limits=limits) as client:

        async def _one(j: dict) -> None:
            url = j["apply_link"]
            host = urlsplit(url).netloc
            hsem = host_sems.setdefault(host, asyncio.Semaphore(settings.MNC_PER_HOST_CONCURRENCY))
            async with sem:
                rec = await fetch_detail(url, client, host_sem=hsem, log=log_)
            stats.detail_fetched += 1
            if rec.status == "ok":
                stats.detail_ok += 1
            elif rec.status == "blocked":
                stats.detail_blocked += 1
            out[j["id"]] = rec

        await asyncio.gather(*(_one(j) for j in todo))
    return out


def enrich_jobs(db: JobDB, **kwargs: Any) -> EnrichStats:
    """Sync entry point (CLI). Inside a running event loop use :func:`enrich_jobs_async`."""
    return asyncio.run(enrich_jobs_async(db, **kwargs))


async def enrich_jobs_async(
    db: JobDB,
    *,
    job_ids: Optional[list[str]] = None,
    only_missing: bool = True,
    limit: Optional[int] = None,
    platform: Optional[str] = None,
    use_llm: bool = True,
    settings: Optional[Settings] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> EnrichStats:
    settings = settings or Settings()
    started = time.monotonic()
    stats = EnrichStats()
    say = progress or (lambda _msg: None)
    jobs = db.jobs_needing_enrichment(only_missing=only_missing, limit=limit, platform=platform, job_ids=job_ids)
    stats.considered = len(jobs)
    if not jobs:
        stats.duration_s = time.monotonic() - started
        return stats
    previous = db.get_enrichment_many([j["id"] for j in jobs])

    # 1) structured detail, concurrently
    say(f"structured detail for {len(jobs)} job(s)…")
    fetched = await _fetch_details(jobs, previous, settings, stats, log)

    # 2) LLM preflight
    extractor: Optional[OllamaExtractor] = None
    if use_llm and settings.LLM_ENRICH_ENABLED:
        extractor = OllamaExtractor(url=settings.OLLAMA_URL, model=settings.OLLAMA_MODEL, timeout=settings.LLM_TIMEOUT,
                                    num_ctx=settings.LLM_NUM_CTX, max_input_chars=settings.LLM_MAX_INPUT_CHARS)
        ok, why = extractor.status()
        stats.llm_status = "ok" if ok else why
        if not ok:
            log.warning("llm.skipped", reason=why)
            say(f"LLM skipped: {why}")
            extractor.close()
            extractor = None
    else:
        stats.llm_status = "disabled"

    # 3) per job: LLM (sequential) → resolve → upsert
    now = datetime.now().isoformat()
    for i, j in enumerate(jobs, 1):
        prev = previous.get(j["id"]) or {}
        detail = fetched.get(j["id"]) or _detail_from_row(prev)
        if j["id"] not in fetched and detail is not None and detail.status == "ok":
            stats.detail_reused += 1
        row: dict[str, Any] = {}
        if j["id"] in fetched:
            row.update(detail.to_row())
            row["en_detail_fetched_at"] = now
        elif not prev.get("en_detail_status"):
            row.update({"en_detail_status": "none", "en_detail_source": "", "en_detail_url": j.get("apply_link") or "", "en_detail_fetched_at": now})

        llm_data: Optional[dict] = None
        need, why = _llm_needed(j, detail)
        prev_llm = None
        if prev.get("en_llm_status") == "ok" and prev.get("en_llm_json") and prev.get("en_description_hash") == _hash(j, detail):
            try:
                prev_llm = json.loads(prev["en_llm_json"])
            except ValueError:
                prev_llm = None
        if need and extractor is not None:
            if prev_llm is not None:
                llm_data = prev_llm
                stats.llm_skipped_reason["cached"] = stats.llm_skipped_reason.get("cached", 0) + 1
            else:
                res = extractor.extract(
                    title=j.get("title") or "", company=j.get("company") or "", listing_location=j.get("location") or "",
                    description=(detail.description if detail and detail.description else j.get("description") or ""),
                    structured_locations=[l.display() for l in detail.locations] if detail else [],
                )
                stats.llm_called += 1
                if res.status == "ok":
                    stats.llm_ok += 1
                    llm_data = res.data
                log.info("llm.extracted", job_id=j["id"], status=res.status, ms=res.latency_ms, cities=res.data.get("cities") if res.data else None, dropped=res.dropped or None)
                row.update(_llm_row(res, settings.OLLAMA_MODEL))
        elif need:
            stats.llm_skipped_reason["llm_unavailable"] = stats.llm_skipped_reason.get("llm_unavailable", 0) + 1
            row.update({"en_llm_status": "skipped"})
        else:
            stats.llm_skipped_reason[why] = stats.llm_skipped_reason.get(why, 0) + 1
            if prev_llm is not None:
                llm_data = prev_llm
            elif not prev.get("en_llm_status"):
                row.update({"en_llm_status": "skipped"})

        resolution = resolve(j.get("location") or "", title=j.get("title") or "", description=j.get("description") or "",
                             detail=detail, llm=llm_data)
        row.update(resolution.to_row())
        row["en_enriched_at"] = now
        row["en_description_hash"] = _hash(j, detail)
        stats.__dict__[f"resolved_{resolution.source}"] += 1
        if not resolution.location_ok:
            stats.hidden += 1
        changed = (prev.get("en_location_ok") is not None and prev.get("en_location_ok") != int(resolution.location_ok)) or \
                  (prev.get("en_resolved_work_mode") and prev.get("en_resolved_work_mode") != resolution.work_mode) or \
                  not prev
        db.upsert_enrichment(j["id"], row)
        if changed:
            stats.changed += 1
            db.conn.execute("UPDATE jobs SET priority_bucket = '' WHERE id = ? AND is_duplicate = 0", (j["id"],))
            stats.rescored += 1
        if i % 25 == 0 or i == len(jobs):
            db.conn.commit()
            say(f"{i}/{len(jobs)} · structured {stats.detail_ok} · llm {stats.llm_ok}/{stats.llm_called} · hidden {stats.hidden}")
    db.conn.commit()
    if extractor is not None:
        extractor.close()
    stats.duration_s = time.monotonic() - started
    log.info("enrich.done", **{k: v for k, v in stats.as_dict().items() if k != "llm_skipped_reason"})
    return stats


def _hash(job: dict, detail: Optional[DetailRecord]) -> str:
    text = (detail.description if detail and detail.description else job.get("description") or "") + "|" + (job.get("location") or "")
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]
