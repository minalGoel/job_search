"""Turn raw postings into Jobs — the single place MNC results are filtered.

No filter *logic* lives here: title relevance is ``services.title_filter``
and location acceptance is ``services.location_filter`` (single source of
truth, guidelines §1/§6). Title runs first because it is cheap and rejects
most of a full listing.

Never falls back to ``mnc.delhi_ncr_office`` for an empty location
(known_edge_cases §11: an unknown location must be rejected, not assumed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from models.job import Job
from mnc_careers.ats.base import RawPosting
from mnc_careers.registry import MNC, platform_for
from services.location_filter import explain as explain_location, is_acceptable_location
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


def postings_to_jobs(mnc: MNC, postings: list[RawPosting], log: Any = log) -> tuple[list[Job], FilterStats]:
    stats = FilterStats(fetched=len(postings))
    jobs: list[Job] = []
    seen: set[str] = set()
    platform = platform_for(mnc)
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
            continue
        location = (p.location or "").strip()
        if not is_acceptable_location(location):
            stats.location_rejected += 1
            log.debug(
                "mnc.filtered_location", company=mnc.name, title=title,
                location=location, reason=explain_location(location),
            )
            continue
        jobs.append(
            Job(
                platform=platform,
                title=title,
                company=mnc.name,
                location=location,
                apply_link=url,
                description=(p.description or "").strip() or f"Direct from {mnc.name} careers page",
            )
        )
        stats.matched += 1
    log.debug(
        "mnc.filtered", company=mnc.name, fetched=stats.fetched, invalid=stats.invalid,
        dupes=stats.dupes, title_rejected=stats.title_rejected,
        location_rejected=stats.location_rejected, matched=stats.matched,
        sample_title_reason=explain_title(postings[0].title) if postings else "",
    )
    return jobs, stats
