"""Turn raw postings into Jobs — the single place MNC results are filtered.

No filter *logic* lives here: title relevance is ``services.title_filter``
and location acceptance is ``services.location_filter`` (single source of
truth, guidelines §1/§6). Title runs first because it is cheap and rejects
most of a full listing.

Never falls back to ``mnc.delhi_ncr_office`` for an empty location
(known_edge_cases §11: an unknown location must be rejected, not assumed).

Since Sept 2026 the location verdict comes from ``services.location_resolver`` and
uses the job's *structured detail record* (job page / ATS detail API) when the
caller fetched one — "India (Hybrid)" with a Bangalore office address is rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from models.job import Job
from mnc_careers.ats.base import RawPosting
from mnc_careers.registry import MNC, platform_for
from services.job_detail import DetailRecord
from services.location_resolver import Resolution, resolve
from services.title_filter import explain_title, is_relevant_title

log = structlog.get_logger(__name__)


@dataclass
class FilterStats:
    fetched: int = 0
    invalid: int = 0
    dupes: int = 0
    title_rejected: int = 0
    location_rejected: int = 0
    matched: int = 0
    detail_used: int = 0                      # postings judged with a structured detail record
    # Job.id → job_enrichment columns (structured half + resolution) for every *matched* job,
    # so the caller can upsert them right after insert_job.
    enrichment: dict[str, dict] = field(default_factory=dict)


def postings_to_jobs(
    mnc: MNC,
    postings: list[RawPosting],
    log: Any = log,
    *,
    details: Optional[dict[str, DetailRecord]] = None,
) -> tuple[list[Job], FilterStats]:
    """Title gate → location verdict (services.location_resolver.resolve, which prefers a
    structured detail record over the listing string) → Job.

    ``details`` maps posting URL → DetailRecord fetched by the caller for coarse/passing
    listings; a fetcher may also have left one on ``RawPosting.detail``. Sync and pure:
    all I/O happens before this is called.
    """
    platform = platform_for(mnc)
    stats = FilterStats(fetched=len(postings))
    jobs: list[Job] = []
    seen: set[str] = set()
    details = details or {}
    for p in postings:
        title = (p.title or "").strip()
        url = (p.url or "").strip()
        if not (title and url):
            stats.invalid += 1
            continue
        if url in seen:
            stats.dupes += 1
            continue
        seen.add(url)
        if not is_relevant_title(title):
            stats.title_rejected += 1
            log.debug("mnc.filtered_title", company=mnc.name, title=title, reason=explain_title(title))
            continue
        location = (p.location or "").strip()
        detail = details.get(url) or (p.detail if isinstance(p.detail, DetailRecord) else None)
        if detail is not None and detail.status == "ok":
            stats.detail_used += 1
        res: Resolution = resolve(location, title=title, description=p.description or "", detail=detail)
        if not res.location_ok:
            stats.location_rejected += 1
            log.debug("mnc.filtered_location", company=mnc.name, title=title, location=location, reason=res.reason)
            continue
        job = Job(
            platform=platform,
            title=title,
            company=mnc.name,
            location=location,
            apply_link=url,
            description=(p.description or "").strip() or f"Direct from {mnc.name} careers page",
        )
        jobs.append(job)
        stats.matched += 1
        row = {**(detail.to_row() if detail is not None else {}), **res.to_row()}
        stats.enrichment[job.id] = row
    return jobs, stats
