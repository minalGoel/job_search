"""Shared helpers for httpx-only (API) scrapers.

Nothing here touches Playwright. Aggregator scrapers (Adzuna, Jooble,
Careerjet) extend :class:`APIScraper`; the parsing helpers are also used by
the older API scrapers (iimjobs, hirist) so date/ID handling lives in one
place.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from scrapers.base import BaseScraper

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class APIScraper(BaseScraper):
    """Base for scrapers that only need httpx (no browser)."""

    uses_browser: bool = False
    requires_login: bool = False
    HEADERS = DEFAULT_HEADERS


def stable_link(url: str) -> str:
    """Drop query string and fragment so per-request tracking params don't
    change the identity of a listing (Adzuna ``redirect_url``, Jooble
    ``link`` carry session tokens). Returns *url* unchanged if it has no path.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if parts.path in ("", "/"):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def stable_job_id(platform: str, company: str, title: str, url: str) -> str:
    """Same formula as ``Job._compute_id`` but over :func:`stable_link`.

    Used by aggregator scrapers so the stored ``apply_link`` can keep the raw
    (working) redirect URL while the ID stays stable across runs.
    """
    from models.job import _normalize  # local import: models is light but avoid cycles

    raw = f"{platform}|{_normalize(company)}|{_normalize(title)}|{stable_link(url)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def strip_html(text: Optional[str]) -> str:
    """Remove tags (Adzuna wraps matched words in ``<strong>``), unescape
    entities and collapse whitespace."""
    if not text:
        return ""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", text))).strip()


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Best-effort ISO-8601 / RFC-2822 → ``date``.

    Handles ``Z`` suffixes, 7-digit fractional seconds (Jooble emits
    ``2025-09-15T00:00:00.0000000`` which ``fromisoformat`` rejects), space
    separators (Careerjet ``2025-09-16 07:54:07``) and RFC-2822 strings.
    Returns ``None`` on anything unparseable — never raises.
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        iso = s.replace("Z", "+00:00")
        # trim fractional seconds to 6 digits
        iso = re.sub(r"(\.\d{6})\d+", r"\1", iso)
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).date()
    except (TypeError, ValueError, IndexError):
        return None


def parse_epoch(value: Any) -> Optional[date]:
    """Unix timestamp in seconds *or* milliseconds → ``date``.

    Field names like ``createdTime`` are ambiguous; anything above 1e11 is
    treated as milliseconds (1e11 s ≈ year 5138, so no real seconds value
    reaches it). Returns ``None`` on garbage.
    """
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if ts > 10**11:
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def format_inr_salary(lo: Any, hi: Any, *, predicted: bool = False) -> Optional[str]:
    """``(1200000, 1800000)`` → ``"₹12 - 18 LPA"`` (``" (est.)"`` when predicted).

    Returns ``None`` unless both bounds are positive numbers.
    """
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if lo_f <= 0 or hi_f <= 0:
        return None
    lo_l, hi_l = lo_f / 100_000, hi_f / 100_000

    def _fmt(x: float) -> str:
        return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"

    text = f"₹{_fmt(lo_l)} - {_fmt(hi_l)} LPA" if _fmt(lo_l) != _fmt(hi_l) else f"₹{_fmt(lo_l)} LPA"
    return text + (" (est.)" if predicted else "")
