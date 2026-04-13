from __future__ import annotations

"""
services/title_filter.py — Single source of truth for job title relevance.

Rule: a title must contain both 'product' AND 'manager' (case-insensitive).
All ingestion paths go through JobDB.insert_job(), which calls is_relevant_title()
before persisting — no per-scraper duplication needed.
"""


def is_relevant_title(title: str) -> bool:
    """Return True if the title contains both 'product' and 'manager'."""
    if not title:
        return False
    lower = title.lower()
    return "product" in lower and "manager" in lower
