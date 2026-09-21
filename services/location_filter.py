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
  8. (Sept 2026) A string that ends in a non-India country is rejected even if it
     contains an "NCR" token (Manila's NCR); "Remote - <US state>" is a US role;
     diacritics are folded ("Haryāna" == "haryana"); every country name/ISO code
     is known, not a hand list.
"""
from __future__ import annotations

import re
import unicodedata

# ── Token sets ────────────────────────────────────────────────────────────────

NCR_TOKENS = (
    "delhi ncr", "delhi-ncr", "delhi/ncr",
    "new delhi", "newdelhi",
    "delhi",
    "ncr",
    "gurugram", "gurgaon", "gurgoan", "gurugaon", "gurgram", "ggn",  # Gurgaon + common misspellings/abbrev.
    "cyber city", "cybercity", "udyog vihar", "sohna road", "golf course road", "manesar",  # Gurgaon localities
    "noida", "greater noida",
    "faridabad", "ghaziabad",  # NCR peripheral cities
)

HYBRID_TOKENS = ("hybrid", "flexible location", "flex location")

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
    "visakhapatnam", "vizag",
    "goa", "panaji", "margao",
    "nashik", "nagpur", "aurangabad", "kolhapur", "solapur",
    "surat", "vadodara", "baroda", "rajkot", "gandhinagar",
    "lucknow", "kanpur", "agra", "varanasi", "prayagraj", "allahabad", "gorakhpur", "bareilly", "aligarh",
    "patna", "ranchi", "jamshedpur", "dhanbad", "raipur", "bhubaneswar", "cuttack", "guwahati", "siliguri", "durgapur",
    "mysore", "mysuru", "mangalore", "mangaluru", "hubli", "hubballi", "belgaum", "belagavi",
    "vijayawada", "tirupati", "guntur", "nellore", "warangal", "kakinada",
    "madurai", "trichy", "tiruchirappalli", "salem", "tirupur", "erode", "vellore", "hosur", "sriperumbudur",
    "pondicherry", "puducherry", "thrissur", "kozhikode", "calicut",
    "dehradun", "haridwar", "roorkee", "shimla", "jammu", "srinagar",
    "amritsar", "ludhiana", "jalandhar", "zirakpur", "panchkula",
    "udaipur", "jodhpur", "ajmer", "kota", "gwalior", "jabalpur",
    "panipat", "karnal", "ambala", "rohtak",  # Haryana but outside NCR
)

# State-level India locations that are not NCR ("Karnataka, India", "MH, India"). Codes are
# only honoured as a whole comma-separated segment. Haryana / Uttar Pradesh / Delhi are
# left out on purpose: they contain NCR and a bare "Haryana, India" is an open question.
INDIA_NON_NCR_REGIONS = (
    "maharashtra", "karnataka", "tamil nadu", "tamilnadu", "telangana", "andhra pradesh", "kerala", "west bengal",
    "gujarat", "rajasthan", "punjab", "madhya pradesh", "odisha", "orissa", "bihar", "jharkhand", "assam",
    "chhattisgarh", "uttarakhand", "himachal pradesh", "jammu and kashmir",
)
INDIA_NON_NCR_REGION_CODES = ("mh", "ka", "tn", "ts", "ap", "kl", "wb", "gj", "rj", "pb", "mp", "od", "jh", "cg", "hp")

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

# Whole-word country names / ISO-ish codes that mark a role as outside India even
# when phrased as "remote" ("Remote, US", "Ontario, CAN - Remote", "Remote - Estonia").
# Codes are limited to ones that don't collide with ordinary words in addresses.
# Every country except India, as written in job locations (lower-case, diacritics folded).
NON_INDIA_COUNTRIES = (
    "afghanistan", "albania", "algeria", "andorra", "angola", "argentina", "armenia", "australia", "austria",
    "azerbaijan", "bahamas", "bahrain", "bangladesh", "barbados", "belarus", "belgium", "belize", "benin", "bhutan",
    "bolivia", "bosnia", "bosnia and herzegovina", "botswana", "brazil", "brunei", "bulgaria", "burkina faso",
    "burundi", "cambodia", "cameroon", "canada", "cape verde", "chad", "chile", "china", "colombia", "congo",
    "costa rica", "croatia", "cuba", "cyprus", "czechia", "czech republic", "denmark", "djibouti", "dominican republic",
    "ecuador", "egypt", "el salvador", "estonia", "ethiopia", "fiji", "finland", "france", "gabon", "georgia",
    "germany", "ghana", "greece", "guatemala", "guinea", "haiti", "honduras", "hong kong", "hongkong", "hungary",
    "iceland", "indonesia", "iran", "iraq", "ireland", "israel", "italy", "ivory coast", "jamaica", "japan", "jordan",
    "kazakhstan", "kenya", "kosovo", "kuwait", "kyrgyzstan", "laos", "latvia", "lebanon", "liberia", "libya",
    "liechtenstein", "lithuania", "luxembourg", "macau", "madagascar", "malawi", "malaysia", "maldives", "mali",
    "malta", "mauritius", "mexico", "moldova", "monaco", "mongolia", "montenegro", "morocco", "mozambique",
    "myanmar", "namibia", "nepal", "netherlands", "new zealand", "nicaragua", "niger", "nigeria", "north macedonia",
    "norway", "oman", "pakistan", "panama", "papua new guinea", "paraguay", "peru", "philippines", "poland",
    "portugal", "puerto rico", "qatar", "romania", "russia", "rwanda", "saudi arabia", "senegal", "serbia",
    "singapore", "slovakia", "slovenia", "somalia", "south africa", "south korea", "korea", "spain", "sri lanka",
    "sudan", "sweden", "switzerland", "syria", "taiwan", "tajikistan", "tanzania", "thailand", "trinidad", "tunisia",
    "turkey", "turkiye", "turkmenistan", "uganda", "ukraine", "united arab emirates", "uae", "united kingdom",
    "great britain", "britain", "england", "scotland", "wales", "northern ireland", "united states", "usa",
    "united states of america", "uruguay", "uzbekistan", "venezuela", "vietnam", "yemen", "zambia", "zimbabwe",
    # regions that never include India
    "americas", "north america", "latin america", "europe", "asia pacific", "middle east",
)

# ISO-2 codes that are safe as whole words in a location string. Deliberately absent:
# "in" (India), "or"/"me"/"no"/"at"/"be"/"it"/"id" (ordinary words), "hr" (Haryana), "tn" (Tamil Nadu),
# "ka"/"mh"/"up"/"dl" (Indian states).
NON_INDIA_COUNTRY_CODES = (
    "us", "usa", "u.s.", "u.s.a.", "uk", "gb", "can", "au", "nz", "eu", "sg", "jp", "hk", "ae", "za", "br", "mx",
    "pl", "ie", "de", "fr", "nl", "ch", "se", "dk", "fi", "ee", "cz", "pt", "co", "gr", "bg", "ph", "ma", "ro",
    "hu", "tr", "ar", "cl", "my", "th", "vn", "kr", "tw", "il", "sa", "qa", "eg", "ng", "ke", "ca", "ua", "rs",
    "sk", "si", "lt", "lv", "lu", "es", "cn", "pe", "ve", "nz", "kz",
)

_NON_INDIA_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in sorted(set(NON_INDIA_COUNTRIES) | set(NON_INDIA_COUNTRY_CODES), key=len, reverse=True)) + r")\b"
)

# "Remote - DC", "Remote in TX", "Remote (CA)": a US state after a remote marker is a US role.
_US_STATE_CODES = (
    "al ak az ar ca co ct dc de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok "
    "or pa ri sc sd tn tx ut vt va wa wv wi wy"
).split()
_REMOTE_US_STATE_RE = re.compile(
    r"\b(?:remote|wfh|work from home)\b\s*(?:[-–—,:/(]|in\b)\s*(?:" + "|".join(_US_STATE_CODES) + r")\b"
)

_TAIL_SPLIT_RE = re.compile(r"\s*(?:,|\||;|\s[-–—]\s|/)\s*")
_PAREN_RE = re.compile(r"\([^)]*\)")


def _non_ncr_region(norm: str) -> str:
    """'Karnataka, India' → 'karnataka'; 'MH, India' → 'mh' (codes only as a whole segment)."""
    for r in INDIA_NON_NCR_REGIONS:
        if re.search(r"\b" + re.escape(r) + r"\b", norm):
            return r
    for seg in _TAIL_SPLIT_RE.split(_PAREN_RE.sub(" ", norm)):
        if seg.strip(" .") in INDIA_NON_NCR_REGION_CODES:
            return seg.strip(" .")
    return ""


def _tail_country(norm: str) -> str:
    """The country a location string *ends* with ('Muntinlupa, NCR, ph' → 'ph'), or ''.

    Only the last comma/dash-separated segment is inspected, so 'Gurugram · US shift'
    is not mistaken for a US role."""
    parts = [p for p in _TAIL_SPLIT_RE.split(_PAREN_RE.sub(" ", norm)) if p and p.strip()]
    if not parts:
        return ""
    tail = parts[-1].strip(" .")
    if tail in NON_INDIA_COUNTRIES or tail in NON_INDIA_COUNTRY_CODES:
        return tail
    return ""


# Canonical spellings so the filter, the resolver and the dashboard agree on a city.
CITY_ALIASES = {
    "bengaluru": "bangalore", "bangalore": "bangalore", "bangaluru": "bangalore",
    "gurugram": "gurgaon", "gurgaon": "gurgaon", "gurgoan": "gurgaon", "gurugaon": "gurgaon", "gurgram": "gurgaon", "ggn": "gurgaon",
    "new delhi": "delhi", "newdelhi": "delhi", "delhi": "delhi", "delhi ncr": "delhi", "delhi-ncr": "delhi",
    "greater noida": "greater noida", "noida": "noida", "faridabad": "faridabad", "ghaziabad": "ghaziabad",
    "bombay": "mumbai", "mumbai": "mumbai", "navi mumbai": "navi mumbai",
    "madras": "chennai", "chennai": "chennai", "calcutta": "kolkata", "kolkata": "kolkata",
    "cochin": "kochi", "kochi": "kochi", "trivandrum": "thiruvananthapuram", "thiruvananthapuram": "thiruvananthapuram",
    "secunderabad": "hyderabad", "hyderabad": "hyderabad", "pune": "pune", "poona": "pune",
}


def canonical_city(name: str | None) -> str:
    """'Bengaluru' → 'bangalore'; unknown names come back normalised but otherwise unchanged."""
    n = _normalize(name or "")
    return CITY_ALIASES.get(n, n)


def is_ncr_city(name: str | None) -> bool:
    return canonical_city(name) in {"delhi", "gurgaon", "noida", "greater noida", "faridabad", "ghaziabad"} or _contains_any(_normalize(name or ""), NCR_TOKENS)


def _fold(text: str) -> str:
    """Strip diacritics: 'Haryāna' → 'haryana', 'Mahārāshtra' → 'maharashtra' (Workday/Phenom
    location strings carry them; the city lists below don't)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _normalize(loc: str) -> str:
    if not loc:
        return ""
    return _WHITESPACE_RE.sub(" ", _fold(loc).strip().lower())


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
    if _contains_any(norm, REMOTE_EXCLUSIONS) or _REMOTE_US_STATE_RE.search(norm):
        return False

    # Rule 0: a string that *ends* in another country is that country's role even when it
    # contains an NCR-looking token — "Muntinlupa, NCR, ph", "Taguig, National Capital
    # Region (NCR), Philippines". An explicit "India" anywhere still wins (multi-country posts).
    if not _INDIA_WORD_RE.search(norm) and _tail_country(norm):
        return False

    # Rule 1: NCR tokens always accepted
    if _contains_any(norm, NCR_TOKENS):
        # BUT: if "delhi" appears alongside another India city like "Bengaluru",
        # treat it as a multi-city posting — still counts as NCR.
        return True

    # Rule 6: explicit non-NCR India city or state → reject
    if _contains_any(norm, INDIA_NON_NCR_CITIES) or _non_ncr_region(norm):
        return False

    # Rule 3: "India" named explicitly (country-level posting, or "Remote - India / US")
    # → accept. Checked before the non-India lists so a role open to India AND
    # other countries is not thrown away.
    if _INDIA_WORD_RE.search(norm):
        return True

    # Rule 6: explicit non-India city/country/code → reject
    if _contains_any(norm, NON_INDIA_CITIES) or _NON_INDIA_TOKEN_RE.search(norm):
        return False

    # Rule 2: pure global remote (no country/city qualifier survived the checks above)
    if _contains_any(norm, REMOTE_TOKENS):
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

    if _contains_any(norm, NCR_TOKENS) and (_INDIA_WORD_RE.search(norm) or not _tail_country(norm)):
        return "delhi-ncr"
    if _contains_any(norm, REMOTE_TOKENS) and not _contains_any(norm, NON_INDIA_CITIES) and not _NON_INDIA_TOKEN_RE.search(norm):
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
    if _contains_any(norm, REMOTE_EXCLUSIONS) or _REMOTE_US_STATE_RE.search(norm):
        return f"regional restriction: {loc!r}"
    tail = "" if _INDIA_WORD_RE.search(norm) else _tail_country(norm)
    if tail:
        return f"ends in non-India country {tail!r}: {loc!r}"
    if _contains_any(norm, NCR_TOKENS):
        return "NCR match"
    if _contains_any(norm, INDIA_NON_NCR_CITIES):
        return f"non-NCR India city: {loc!r}"
    if _non_ncr_region(norm):
        return f"non-NCR India state {_non_ncr_region(norm)!r}: {loc!r}"
    if _INDIA_WORD_RE.search(norm):
        return "India (country-level)"
    if _contains_any(norm, NON_INDIA_CITIES):
        return f"non-India city/country: {loc!r}"
    m = _NON_INDIA_TOKEN_RE.search(norm)
    if m:
        return f"non-India country token {m.group(0)!r}: {loc!r}"
    if _contains_any(norm, REMOTE_TOKENS):
        return "pure remote"
    return f"unrecognised: {loc!r}"


def work_mode(loc: str | None, title: str | None = "", description: str | None = "") -> str:
    """Derive remote | hybrid | onsite | unknown from location (+ title/description hints).

    The user prefers remote/hybrid roles; scoring rewards them and the dashboard
    filters on this value. Location text wins over description text.
    """
    norm_loc = _normalize(loc or "")
    norm_title = _normalize(title or "")
    head = _normalize((description or "")[:600])
    if _contains_any(norm_loc, HYBRID_TOKENS) or _contains_any(norm_title, HYBRID_TOKENS):
        return "hybrid"
    if _contains_any(norm_loc, REMOTE_TOKENS) or _contains_any(norm_title, REMOTE_TOKENS):
        return "remote"
    if _contains_any(head, HYBRID_TOKENS):
        return "hybrid"
    if "fully remote" in head or "remote-first" in head or "remote first" in head or "100% remote" in head:
        return "remote"
    if _contains_any(norm_loc, NCR_TOKENS) or _contains_any(norm_loc, INDIA_NON_NCR_CITIES) or _contains_any(norm_loc, NON_INDIA_CITIES):
        return "onsite"
    return "unknown"
