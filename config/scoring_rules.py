from __future__ import annotations

# ---------------------------------------------------------------------------
# Title weights — applied to lowercased title, first match wins
# Positive values boost relevance_score; negative values demote it.
# ---------------------------------------------------------------------------
TITLE_WEIGHTS: list[tuple[str, int]] = [
    # Negative / off-target specific matches first. Since the title GATE is now
    # "anything with product" (config/search_params.py), the non-PM product
    # families are demoted here rather than dropped, and surfaced via categories.
    ("associate product manager", -25),
    ("associate pm", -25),
    ("implementation manager", -35),
    ("business analyst", -35),
    ("project manager", -40),
    ("program manager", -20),
    ("product marketing", -30),
    ("product designer", -35),
    ("product design", -30),
    ("product owner", -12),
    ("product analyst", -20),
    ("product operations", -20),
    ("product ops", -20),
    ("product support", -35),
    ("product specialist", -30),
    ("product engineer", -35),
    ("product developer", -35),
    ("scrum master", -30),
    # Positive matches — most specific first
    ("principal product manager", 34),
    ("staff product manager", 32),
    ("group product manager", 32),
    ("senior product manager", 30),
    ("lead product manager", 28),
    ("head of product", 28),
    ("director of product", 26),
    ("director, product", 26),
    ("director product", 26),
    ("vp product", 22),
    ("vp of product", 22),
    ("chief product officer", 18),
    ("product manager ii", 25),
    ("product manager 2", 25),
    ("product lead", 22),
    ("product manager", 18),      # keep after the specific PM variants
    ("product management", 14),   # generic "…, Product Management" titles
]

# ---------------------------------------------------------------------------
# Work mode — the user prefers remote/hybrid roles (services/location_filter.work_mode)
# ---------------------------------------------------------------------------
WORK_MODE_BONUS: dict[str, int] = {
    "remote": 12,
    "hybrid": 10,
    "onsite": 0,
    "unknown": 0,
}

# ---------------------------------------------------------------------------
# Keyword scoring — searched in combined title + description (lowercased)
# ---------------------------------------------------------------------------
POSITIVE_KEYWORDS: list[str] = [
    "b2b", "saas", "platform", "growth", "monetization",
    "retention", "pricing", "experimentation", "0-1", "zero to one",
    "user research", "product-led", "plg", "fintech", "edtech",
    "marketplace", "api", "enterprise", "gtm", "go-to-market",
]
POSITIVE_KEYWORD_SCORE: int = 5
POSITIVE_KEYWORD_CAP: int = 20   # max additive contribution

NEGATIVE_KEYWORDS: list[str] = [
    "support", "operations", "implementation", "client delivery",
    "presales", "pre-sales", "service delivery", "customer success",
    "project coordination", "delivery manager",
]
NEGATIVE_KEYWORD_SCORE: int = -5

# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
LOCATION_ALLOWLIST: list[str] = [
    "delhi ncr", "delhi", "gurugram", "gurgaon", "noida",
    "new delhi", "remote", "work from home", "wfh", "hybrid",
]
LOCATION_MATCH_SCORE: int = 15
LOCATION_MISMATCH_SCORE: int = -10

# ---------------------------------------------------------------------------
# Recency — (max_days_old, bonus_points)
# ---------------------------------------------------------------------------
RECENCY_BONUSES: list[tuple[int, int]] = [
    (3,  15),   # 0-3 days
    (7,  10),   # 4-7 days
    (14,  5),   # 8-14 days
    (30,  0),   # 15-30 days
    (999, -5),  # 31+ days — stale
]

# ---------------------------------------------------------------------------
# Known high-paying companies (normalized slugs — no punctuation, lowercase)
# ---------------------------------------------------------------------------
HIGH_PAYING_COMPANIES: frozenset[str] = frozenset({
    # Big tech
    "google", "microsoft", "amazon", "meta", "apple", "adobe",
    "salesforce", "oracle", "sap", "ibm", "atlassian", "servicenow",
    "workday", "snowflake", "databricks", "stripe", "twilio",
    "linkedin", "netflix", "spotify", "uber", "airbnb",
    # Consulting / strategy
    "mckinsey", "bain", "bcg", "deloitte", "accenture", "thoughtworks",
    # Indian tech unicorns / top startups
    "flipkart", "meesho", "razorpay", "zepto", "blinkit", "cred",
    "groww", "upstox", "zomato", "swiggy", "byju", "unacademy",
    "paytm", "phonepe", "nykaa", "urban company", "urbancompany",
    "moengage", "clevertap", "chargebee", "freshworks", "zoho",
    "browserstack", "postman", "hasura", "setu", "swyp",
})
HIGH_PAYING_COMPANY_SCORE: int = 35

# ---------------------------------------------------------------------------
# Salary likelihood component scores (0-100 range)
# ---------------------------------------------------------------------------
SALARY_SCORES: dict[str, int] = {
    "high_paying_company": 35,
    "mnc": 30,
    "series_c_plus": 25,
    "series_b": 20,
    "series_a": 15,
    "seed": 5,
    "senior_pm_title": 20,
    "pm_ii_title": 15,
    "direct_source": 10,
}

# ---------------------------------------------------------------------------
# Company quality component scores (0-100 range)
# ---------------------------------------------------------------------------
COMPANY_QUALITY_SCORES: dict[str, int] = {
    "mnc": 20,
    "target_mnc": 15,        # company is on the user's MNC list (hq_country set from mnc_input.csv)
    "recent_funding": 15,
    "yc_company": 15,
    "recent_yc_batch": 10,
    "multiple_pm_roles": 10,
    "direct_source": 10,
    "vc_backed": 10,
}

# ---------------------------------------------------------------------------
# Priority score weights (must sum to 1.0)
# semantic weight uses sentence-transformers embeddings; gracefully 0 if not installed.
# ---------------------------------------------------------------------------
PRIORITY_WEIGHTS: dict[str, float] = {
    "relevance": 0.35,
    "salary": 0.28,
    "warmth": 0.13,
    "company_quality": 0.09,
    "semantic": 0.15,
}

# ---------------------------------------------------------------------------
# Priority bucket thresholds (score >= threshold -> bucket)
# ---------------------------------------------------------------------------
BUCKET_THRESHOLDS: list[tuple[str, int]] = [
    ("must_apply", 80),
    ("high", 65),
    ("medium", 50),
    ("low", 0),
]

# ---------------------------------------------------------------------------
# Platforms treated as direct / authoritative sources
# ---------------------------------------------------------------------------
DIRECT_SOURCE_PLATFORMS: frozenset[str] = frozenset({
    "ycombinator", "wellfound", "weekday", "mnc_careers", "vc_portals",
})

# ---------------------------------------------------------------------------
# Agency / staffing detection keywords (matched against company name)
# ---------------------------------------------------------------------------
AGENCY_KEYWORDS: list[str] = [
    "staffing", "recruitment", "recruiter", "manpower",
    "talent", "hr solutions", "consulting", "headhunter",
]

# ---------------------------------------------------------------------------
# IIT top-7 alumni keywords for warmth scoring
# ---------------------------------------------------------------------------
IIT_TOP7_KEYWORDS: list[str] = [
    "iit bombay", "iit delhi", "iit madras", "iit kanpur",
    "iit kharagpur", "iit roorkee", "iit guwahati",
    "iitb", "iitd", "iitm", "iitk", "iitkgp", "iitr", "iitg",
]
