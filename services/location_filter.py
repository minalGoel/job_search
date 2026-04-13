"""
services/location_filter.py — Single source of truth for location validation.

Rules (per user decisions, Apr 7 2026):
  1. Delhi NCR tokens → ACCEPT
  2. Pure global "Remote" / "Anywhere" → ACCEPT
  3. "Remote — India" / "Work from Home — Anywhere" → ACCEPT
  4. "Remote — <non-NCR city>" or "Remote — US only" → REJECT
  5. Empty string / None → REJECT
  6. Any specific non-NCR city (London, Bangalore, SF, ...) → REJECT
  7. Hybrid counts only if the paired city is in NCR
"""
from __future__ import annotations

import re

# ── Token sets ────────────────────────────────────────────────────────────────

NCR_TOKENS = (
    "delhi ncr", "delhi-ncr", "delhi/ncr",
    "new delhi", "newdelhi",
    "delhi",
    "ncr",
    "gurugram", "gurgaon",
    "noida",
    "faridabad", "ghaziabad",  # NCR peripheral cities
)

REMOTE_TOKENS = (
    "remote",
    "anywhere",
    "worldwide",
    "global",
    "work from home",
    "work-from-home",
    "wfh",
    "distributed",
)

# Explicit regional restrictions that kill a "Remote" claim
REMOTE_EXCLUSIONS = (
    "us only", "usa only", "u.s. only", "u.s.a only",
    "united states only", "us-only", "usa-only",
    "us citizens", "us residents",
    "eu only", "europe only", "uk only", "emea only",
    "apac only", "americas only", "canada only", "latam only",
    "na only", "americas-only",
    # Regional words (without "only") that almost always exclude India
    "emea", "latam",
    "apac (ex ",  # "APAC (ex India)"
    "apac excluding",
    # Dash-separated country codes — "Remote - US", "WFH - USA"
    "- us", "- usa",
    # Parenthesised country codes — "Remote (US)", "Remote (UK)", etc.
    "(us)", "(usa)", "(u.s.)", "(u.s.a.)",
    "(uk)", "(u.k.)", "(eu)", "(emea)",
    "(ca)", "(au)", "(nz)", "(jp)", "(sg)", "(de)", "(fr)",
    # Bracket variants
    "[us]", "[uk]", "[eu]",
)

# India cities that are NOT NCR — explicit rejects because "Remote - Bangalore"
# is a Bangalore role, not a global one.
INDIA_NON_NCR_CITIES = (
    "bangalore", "bengaluru",
    "mumbai", "bombay", "navi mumbai", "thane",
    "hyderabad", "secunderabad",
    "chennai", "madras",
    "pune",
    "kolkata", "calcutta",
    "ahmedabad",
    "jaipur",
    "kochi", "cochin",
    "trivandrum", "thiruvananthapuram",
    "chandigarh", "mohali",
    "indore", "bhopal",
    "coimbatore",
    "visakhapatnam",
    "goa",
)

# Non-India cities (not exhaustive — enough to catch obvious global roles)
NON_INDIA_CITIES = (
    # USA metro areas (including shorthand)
    "bay area", "sf bay", "silicon valley",
    # USA
    "san francisco", "new york", " nyc", "los angeles", " la ", "seattle", "boston",
    "chicago", "austin", "denver", "atlanta", "dallas", "houston", "portland",
    "miami", "washington dc", "san diego", "phoenix", "minneapolis", "nashville",
    "philadelphia", "pittsburgh", "detroit", "salt lake", "san jose", "mountain view",
    "palo alto", "menlo park", "sunnyvale", "cupertino", "redwood city",
    # Europe
    "london", "berlin", "paris", "amsterdam", "dublin", "madrid", "barcelona",
    "munich", "zurich", "stockholm", "oslo", "copenhagen", "helsinki",
    "lisbon", "milan", "rome", "vienna", "prague", "warsaw", "brussels",
    "luxembourg", "frankfurt", "hamburg", "edinburgh", "manchester",
    # Americas (non-US)
    "toronto", "vancouver", "montreal", "ottawa",
    "mexico city", "sao paulo", "buenos aires", "santiago",
    # APAC
    "sydney", "melbourne", "brisbane", "perth", "auckland", "wellington",
    "tokyo", "osaka", "kyoto", "seoul", "busan",
    "hong kong", "singapore", "bangkok", "jakarta", "manila", "kuala lumpur",
    "taipei", "shanghai", "beijing", "shenzhen", "guangzhou",
    # Middle East
    "dubai", "abu dhabi", "doha", "riyadh", "jeddah",
    "tel aviv", "jerusalem", "haifa",
    # Africa
    "cape town", "johannesburg", "nairobi", "lagos", "cairo",
    # Countries (when given without a city)
    "united states", " usa", " u.s.", "united kingdom", "germany", "france",
    "spain", "italy", "netherlands", "sweden", "norway", "denmark",
    "switzerland", "australia", "new zealand", "japan", "south korea",
    "china", "philippines", "thailand", "vietnam", "malaysia", "indonesia",
    "brazil", "argentina", "mexico", "canada",
    "israel", "uae", "saudi arabia",
)


# ── Normalisation ─────────────────────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\s+")
_INDIA_WORD_RE = re.compile(r"\bindia\b")


def _normalize(loc: str) -> str:
    if not loc:
        return ""
    return _WHITESPACE_RE.sub(" ", loc.strip().lower())


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


# ── Public API ────────────────────────────────────────────────────────────────

def is_acceptable_location(loc: str | None) -> bool:
    """Return True if this raw location string qualifies for the NCR + global-remote filter.

    See module docstring for rule list.
    """
    if not loc:
        return False  # Decision 2: skip empty

    norm = _normalize(loc)
    if not norm:
        return False

    # Hard excludes on regional restrictions (kills a 'remote' claim)
    if _contains_any(norm, REMOTE_EXCLUSIONS):
        return False

    # Rule 1: NCR tokens always accepted
    if _contains_any(norm, NCR_TOKENS):
        # BUT: if "delhi" appears alongside another India city like "Bengaluru",
        # treat it as a multi-city posting — still counts as NCR.
        return True

    # Rule 6: explicit non-NCR India city → reject
    if _contains_any(norm, INDIA_NON_NCR_CITIES):
        return False

    # Rule 6: explicit non-India city/country → reject
    if _contains_any(norm, NON_INDIA_CITIES):
        return False

    # Rule 2/3: remote check
    is_remote = _contains_any(norm, REMOTE_TOKENS)
    if is_remote:
        # Already filtered out non-NCR cities above, so this is safe.
        return True

    # Rule 3: "India" on its own (without a specific non-NCR city) — accept.
    # This catches "India" as a country-level posting.
    if _INDIA_WORD_RE.search(norm):
        return True

    return False


def normalize_region(loc: str | None) -> str:
    """Normalise a raw location string into a dedup-friendly region key.

    Used by Job.dedup_hash so London-Expedia and Delhi-Expedia hash differently.
    """
    if not loc:
        return "unknown"
    norm = _normalize(loc)
    if not norm:
        return "unknown"

    if _contains_any(norm, NCR_TOKENS):
        return "delhi-ncr"
    if _contains_any(norm, REMOTE_TOKENS) and not _contains_any(norm, NON_INDIA_CITIES):
        return "remote"
    if _contains_any(norm, INDIA_NON_NCR_CITIES):
        # Return the first matching Indian city
        for city in INDIA_NON_NCR_CITIES:
            if city in norm:
                return city
    # Truncate to keep hash stable even for long "Remote, EMEA, APAC ex India" blobs
    return norm[:32]


def explain(loc: str | None) -> str:
    """Human-readable reason for debugging."""
    if not loc:
        return "empty"
    norm = _normalize(loc)
    if _contains_any(norm, REMOTE_EXCLUSIONS):
        return f"regional restriction: {loc!r}"
    if _contains_any(norm, NCR_TOKENS):
        return "NCR match"
    if _contains_any(norm, INDIA_NON_NCR_CITIES):
        return f"non-NCR India city: {loc!r}"
    if _contains_any(norm, NON_INDIA_CITIES):
        return f"non-India city/country: {loc!r}"
    if _contains_any(norm, REMOTE_TOKENS):
        return "pure remote"
    if _INDIA_WORD_RE.search(norm):
        return "India (country-level)"
    return f"unrecognised: {loc!r}"
