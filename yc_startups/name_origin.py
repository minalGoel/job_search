"""
yc_startups/name_origin.py — Classify founder names by probable Indian origin (offline).

Uses trained ML models (first_name_model + last_name_model) with no API limits.
Instant classification, fully offline after first training.
"""
from __future__ import annotations

import json

import structlog

from yc_startups.name_classifier import classify_batch

log = structlog.get_logger(__name__)


async def classify_founders_batch(
    companies: list[dict],
    delay: float = 0.0,  # No need for delays with offline classifier
) -> list[dict]:
    """Classify Indian-origin founders for a batch of YC companies.

    Uses offline ML models (no API rate limits).

    Args:
        companies: Company dicts with keys 'id', 'company_name', and 'founders'
                   (either a JSON string or a list of dicts with a 'name' key).
        delay:     Ignored (kept for backward compatibility). No delays needed.

    Returns:
        List of dicts: {company_id, has_indian_origin_founder, indian_origin_confidence}
        where *indian_origin_confidence* is the max P(India) across all founders.
    """
    results: list[dict] = []

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

        # Classify all founder names in batch
        classifications = classify_batch(names)

        max_confidence = 0.0
        for classification in classifications:
            if classification["is_indian"]:
                max_confidence = max(max_confidence, classification["confidence"])

        has_indian = max_confidence > 0.0
        results.append({
            "company_id": company["id"],
            "has_indian_origin_founder": has_indian,
            "indian_origin_confidence": round(max_confidence, 4),
        })

        if has_indian:
            log.info(
                "name_origin.indian_founder_found",
                company=company.get("company_name", ""),
                confidence=round(max_confidence, 3),
            )

    indian_count = sum(1 for r in results if r["has_indian_origin_founder"])
    log.info(
        "name_origin.batch_done",
        total=len(companies),
        with_founders=len([c for c in companies if c.get("founders")]),
        indian=indian_count,
    )
    return results
