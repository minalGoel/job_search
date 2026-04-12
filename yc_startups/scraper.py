"""
yc_startups/scraper.py — Fetch the full YC company directory.

Primary source: yc-oss GitHub Pages API (free, no auth).
  https://yc-oss.github.io/api/companies/all.json  — 5,690 companies
  https://yc-oss.github.io/api/companies/hiring.json — currently hiring subset

Produces a list of YCCompany objects for storage in the DB.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import httpx
import structlog

from yc_startups.models import YCCompany, _make_slug

log = structlog.get_logger(__name__)

# yc-oss GitHub Pages API — ~5 690 companies, updated regularly
YC_ALL_URL = "https://yc-oss.github.io/api/companies/all.json"
YC_HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"
YC_META_URL = "https://yc-oss.github.io/api/meta.json"

# Batch name normalisation: "Winter 2024" -> "W24", "Summer 2023" -> "S23"
_SEASON_PREFIX = {
    "winter": "W", "summer": "S", "fall": "F", "spring": "Sp",
}


def _normalise_batch(raw: str) -> str:
    """Normalise 'Winter 2024' -> 'W24', pass through 'W24' unchanged."""
    if not raw:
        return ""
    # Already short form?
    if re.match(r"^[WSF]\d{2}$", raw) or re.match(r"^Sp\d{2}$", raw):
        return raw
    parts = raw.strip().split()
    if len(parts) == 2:
        season = parts[0].lower()
        year = parts[1]
        prefix = _SEASON_PREFIX.get(season, season[0].upper())
        short_year = year[-2:] if len(year) == 4 else year
        return f"{prefix}{short_year}"
    return raw


async def sync_yc_directory(
    batch_filter: list[str] | None = None,
    limit: int = 0,
) -> list[YCCompany]:
    """Fetch YC companies from the yc-oss API.

    Args:
        batch_filter: Only keep companies from these batches (e.g. ["S24","W24"]).
                      Empty / None means keep all. Accepts both "S24" and
                      "Summer 2024" formats.
        limit: Max companies to return. 0 = unlimited.

    Returns:
        List of YCCompany objects ready for DB insertion.
    """
    # Normalise filter to short form for matching
    normalised_filter: set[str] | None = None
    if batch_filter:
        normalised_filter = {_normalise_batch(b) for b in batch_filter}

    try:
        companies = await _fetch_all_companies(normalised_filter)
        log.info("yc.sync.ok", count=len(companies))
    except Exception:
        log.exception("yc.sync.fetch_failed")
        return []

    if limit > 0:
        companies = companies[:limit]

    now = datetime.now().isoformat()
    for c in companies:
        c.last_refreshed_at = now

    return companies


async def _fetch_all_companies(
    batch_filter: set[str] | None,
) -> list[YCCompany]:
    """Fetch from yc-oss GitHub Pages API."""
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        resp = await client.get(YC_ALL_URL)
        resp.raise_for_status()
        items = resp.json()

    if not isinstance(items, list):
        log.error("yc.sync.unexpected_shape", type=type(items).__name__)
        return []

    companies: list[YCCompany] = []
    for item in items:
        c = _parse_item(item)
        if not c:
            continue
        if batch_filter and c.batch not in batch_filter:
            continue
        companies.append(c)

    return companies


def _parse_item(item: dict) -> YCCompany | None:
    """Parse a single company from the yc-oss JSON."""
    name = (item.get("name") or "").strip()
    if not name:
        return None

    slug = item.get("slug") or _make_slug(name)
    batch_raw = item.get("batch") or ""
    batch = _normalise_batch(batch_raw)

    # Build location from all_locations or regions
    location = item.get("all_locations") or ""
    if not location:
        regions = item.get("regions") or []
        location = ", ".join(regions) if isinstance(regions, list) else str(regions)

    # Subindustry: use the structured field, or join tags
    subindustry = item.get("subindustry") or ""
    if not subindustry:
        tags = item.get("tags") or []
        subindustry = ", ".join(tags) if isinstance(tags, list) else str(tags)

    return YCCompany(
        name=name,
        slug=slug,
        description=item.get("one_liner") or "",
        long_description=item.get("long_description") or "",
        batch=batch,
        website=item.get("website") or "",
        hq_location=location,
        team_size=str(item.get("team_size") or ""),
        industry=item.get("industry") or "",
        subindustry=subindustry,
        status=item.get("status") or "Active",
        logo_url=item.get("small_logo_thumb_url") or "",
        is_hiring=bool(item.get("isHiring")),
    )
