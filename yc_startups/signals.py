"""
yc_startups/signals.py — Detect hiring signals for YC companies.

Checks multiple sources to determine if a YC company is actively
hiring for PM roles:
  1. YC Work at a Startup (workatastartup.com) — YC's official job board
  2. Company careers pages (website + /careers, /jobs patterns)
  3. Cross-reference with already-scraped jobs in jobs.db
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import httpx
import structlog

from yc_startups.models import YCHiringSignal

log = structlog.get_logger(__name__)

PM_TITLE_PATTERNS = re.compile(
    r"product\s*manager|head\s*of\s*product|director.*product|vp.*product|"
    r"chief\s*product|product\s*lead",
    re.IGNORECASE,
)


async def check_hiring_signals(
    companies: list[dict],
    db: object | None = None,
) -> list[YCHiringSignal]:
    """Check hiring signals for a batch of YC companies.

    Args:
        companies: List of company dicts from yc_companies table.
        db: Optional JobDB instance for cross-referencing existing jobs.

    Returns:
        List of YCHiringSignal objects.
    """
    signals: list[YCHiringSignal] = []
    now = datetime.now().isoformat()

    # ── 1. Cross-reference with existing scraped jobs ──────────────────
    if db is not None:
        db_signals = _check_existing_jobs(companies, db)
        signals.extend(db_signals)
        log.info("yc.signals.db_xref", matches=len(db_signals))

    # ── 2. Check companies that self-report is_hiring from YC API ─────
    for company in companies:
        if company.get("is_hiring"):
            signals.append(YCHiringSignal(
                company_id=company["id"],
                signal_type="yc_api_flag",
                signal_source="yc-oss/api",
                signal_detail="Company flagged as hiring in YC directory",
                checked_at=now,
            ))

    # ── 3. Batch-check careers page existence ─────────────────────────
    careers_signals = await _check_careers_pages(companies)
    signals.extend(careers_signals)
    log.info("yc.signals.careers_check", found=len(careers_signals))

    return signals


def _check_existing_jobs(companies: list[dict], db: object) -> list[YCHiringSignal]:
    """Cross-reference YC companies with already-scraped job listings."""
    from services.scoring import _company_slug

    signals: list[YCHiringSignal] = []
    now = datetime.now().isoformat()

    # Build slug -> company mapping
    slug_to_company: dict[str, dict] = {}
    for c in companies:
        slug = _company_slug(c.get("company_name") or c.get("name", ""))
        if slug:
            slug_to_company[slug] = c

    if not slug_to_company:
        return signals

    # Get all non-duplicate jobs from DB
    all_jobs = db.get_all_jobs()  # type: ignore[union-attr]
    for job in all_jobs:
        job_slug = _company_slug(job.get("company", ""))
        if not job_slug:
            continue
        # Check if this job belongs to a YC company
        matched_company = slug_to_company.get(job_slug)
        if not matched_company:
            # Try partial matching
            for yc_slug, yc_company in slug_to_company.items():
                if yc_slug in job_slug or job_slug in yc_slug:
                    matched_company = yc_company
                    break
        if not matched_company:
            continue

        is_pm = bool(PM_TITLE_PATTERNS.search(job.get("title", "")))
        detail = f"{'PM' if is_pm else 'Non-PM'} role on {job.get('platform', '?')}: {job.get('title', '')}"

        signals.append(YCHiringSignal(
            company_id=matched_company["id"],
            signal_type="scraped_job",
            signal_source=job.get("platform", "unknown"),
            signal_date=job.get("scraped_at", "")[:10],
            signal_detail=detail,
            checked_at=now,
        ))

    return signals


async def _check_careers_pages(companies: list[dict]) -> list[YCHiringSignal]:
    """Quick HEAD/GET check on common careers page URLs."""
    signals: list[YCHiringSignal] = []
    now = datetime.now().isoformat()

    # Build list of URLs to check
    checks: list[tuple[dict, str]] = []
    for c in companies:
        website = (c.get("website") or "").rstrip("/")
        if not website:
            continue
        if not website.startswith("http"):
            website = f"https://{website}"
        for suffix in ["/careers", "/jobs", "/open-positions"]:
            checks.append((c, f"{website}{suffix}"))

    if not checks:
        return signals

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20),
    ) as client:
        for company, url in checks:
            try:
                resp = await client.head(url)
                if resp.status_code < 400:
                    signals.append(YCHiringSignal(
                        company_id=company["id"],
                        signal_type="careers_page",
                        signal_source=url,
                        signal_detail=f"Careers page found: {url}",
                        checked_at=now,
                    ))
                    break  # One signal per company is enough
            except Exception:
                continue  # Network error, skip

    return signals
