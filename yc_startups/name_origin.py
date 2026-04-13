"""
yc_startups/name_origin.py — Classify founder names by probable Indian origin.

Uses the nationalize.io free API (no auth, 1000 req/day on free tier).
Caches first-name results within a batch to avoid duplicate API calls.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import structlog

log = structlog.get_logger(__name__)

NATIONALIZE_URL = "https://api.nationalize.io/"
INDIA_COUNTRY_ID = "IN"

# P(India) >= this threshold → flagged as probable Indian origin.
# Kept deliberately low (10 %) because many clearly Indian names (Rahul, Priya)
# score 30-60 % while ambiguous South-Asian names score 10-20 %.
INDIAN_ORIGIN_THRESHOLD = 0.10


def _first_name(full_name: str) -> str:
    """Return the first token of a name string, stripped of whitespace."""
    parts = full_name.strip().split()
    return parts[0] if parts else ""


async def _india_probability(first_name: str, client: httpx.AsyncClient) -> float:
    """Return nationalize.io's P(Indian origin) for *first_name*.

    Returns 0.0 on any network error so the caller can proceed gracefully.
    """
    if not first_name or len(first_name) < 2:
        return 0.0
    try:
        resp = await client.get(NATIONALIZE_URL, params={"name": first_name.lower()})
        resp.raise_for_status()
        data = resp.json()
        for country in data.get("country") or []:
            if country.get("country_id") == INDIA_COUNTRY_ID:
                return float(country.get("probability", 0.0))
        return 0.0
    except Exception:
        log.debug("name_origin.api_error", name=first_name)
        return 0.0


async def classify_founders_batch(
    companies: list[dict],
    delay: float = 0.25,
) -> list[dict]:
    """Classify Indian-origin founders for a batch of YC companies.

    Args:
        companies: Company dicts with keys 'id', 'company_name', and 'founders'
                   (either a JSON string or a list of dicts with a 'name' key).
        delay:     Seconds between each nationalize.io call (be polite to free API).

    Returns:
        List of dicts: {company_id, has_indian_origin_founder, indian_origin_confidence}
        where *indian_origin_confidence* is the max P(India) across all founders.
    """
    results: list[dict] = []
    name_cache: dict[str, float] = {}  # first_name.lower() → P(India)

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for company in companies:
            founders_raw = company.get("founders") or "[]"
            if isinstance(founders_raw, str):
                try:
                    founders = json.loads(founders_raw)
                except Exception:
                    founders = []
            else:
                founders = list(founders_raw)

            names = [f.get("name", "") for f in founders if f.get("name")]

            if not names:
                results.append({
                    "company_id": company["id"],
                    "has_indian_origin_founder": False,
                    "indian_origin_confidence": 0.0,
                })
                continue

            max_prob = 0.0
            for name in names:
                first = _first_name(name)
                if not first:
                    continue
                key = first.lower()
                if key not in name_cache:
                    prob = await _india_probability(first, client)
                    name_cache[key] = prob
                    await asyncio.sleep(delay)
                else:
                    prob = name_cache[key]
                max_prob = max(max_prob, prob)

            has_indian = max_prob >= INDIAN_ORIGIN_THRESHOLD
            results.append({
                "company_id": company["id"],
                "has_indian_origin_founder": has_indian,
                "indian_origin_confidence": round(max_prob, 4),
            })

            if has_indian:
                log.info(
                    "name_origin.indian_founder_found",
                    company=company.get("company_name", ""),
                    confidence=round(max_prob, 3),
                )

    indian_count = sum(1 for r in results if r["has_indian_origin_founder"])
    log.info(
        "name_origin.batch_done",
        total=len(companies),
        with_founders=len([c for c in companies if c.get("founders")]),
        indian=indian_count,
    )
    return results
