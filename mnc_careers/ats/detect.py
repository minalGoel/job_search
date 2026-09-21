"""ATS detection and URL parsing shared by the scraper and the discovery tool.

Detection is deliberately conservative (host/path patterns that are
unambiguous). Custom-domain deployments (e.g. Eightfold on
``jobs.siemens.com``) are handled by an explicit ``api_type`` override in
the registry after live verification, not by guessing.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# api_type values with a typed fetcher in mnc_careers/ats/
TYPED = ("workday", "greenhouse", "lever", "smartrecruiters", "successfactors", "amazon_jobs", "phenom",
         "oracle_hcm", "radancy", "avature", "eightfold_api")
# recognised but routed to the HTML lane (eightfold: API needs a browser session;
# icims/taleo: no typed fetcher — parked)
HTML_ONLY = ("eightfold", "icims", "taleo", "html")
# Detected from URL shape alone; their fetchers raise NotThisATS on a first-page
# mismatch and the company is rerouted to the HTML lane — so a browser must be up.
SHAPE_DETECTED = ("phenom", "radancy", "avature")

_LOCALE_RE = re.compile(r"^[a-z]{2}[-_][A-Za-z]{2}$")
_SEARCH_PARAM_KEYS = {"q", "searchtext", "keywords", "keyword", "query", "search", "k", "jk", "searchjob", "term", "base_query"}


def detect_ats(url: Optional[str]) -> str:
    """Return the ATS type for *url* or ``""`` when unknown (→ HTML lane)."""
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path or "/"
    query = parts.query.lower()

    if "myworkdayjobs.com" in host or "/wday/cxs/" in path:
        return "workday"
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "eightfold.ai" in host or "/api/apply/v2/jobs" in path:
        return "eightfold"
    if host.endswith("amazon.jobs") or host == "www.amazon.jobs":
        return "amazon_jobs"
    if "oraclecloud.com" in host and ("/hcmui/" in path.lower() or "/hcmrestapi/" in path.lower()):
        return "oracle_hcm"
    if "icims.com" in host:
        return "icims"
    if "taleo.net" in host:
        return "taleo"
    # SuccessFactors career sites: .../search/?q=...&locationsearch=...
    if path.endswith("/search/") and ("q=" in query or "locationsearch" in query or query == ""):
        return "successfactors"
    # Phenom People: /{country}/{lang}/search-results or /job-search-results/
    if re.search(r"/(?:job-)?search-results/?(?:\.html)?$", path, re.I) or "/widgets" == path:
        return "phenom"
    # Radancy / TalentBrew: /search-jobs[/keyword/location]
    if re.search(r"/search-jobs(?:/|$)", path, re.I):
        return "radancy"
    # Avature: …/SearchJobs (also *.avature.net)
    if "avature.net" in host or re.search(r"/searchjobs(?:/|$)", path, re.I):
        return "avature"
    return ""


def strip_search_params(url: str) -> str:
    """Remove keyword-search params so the URL points at the *full listing*.

    The registry's ``?q=product+manager`` URLs are volume hints, not filters
    (guidelines §12) — the primary fetch uses the un-searched listing.
    """
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _SEARCH_PARAM_KEYS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def parse_target(url: str, ats: str) -> dict[str, str]:
    """Extract the identifiers a fetcher needs from a listing/API URL."""
    parts = urlsplit(url)
    host = parts.netloc
    segs = [s for s in parts.path.split("/") if s]
    q = dict(parse_qsl(parts.query, keep_blank_values=True))

    if ats == "workday":
        tenant = host.split(".")[0]
        site = ""
        if "wday" in segs and "cxs" in segs:
            # https://{host}/wday/cxs/{tenant}/{site}/jobs
            i = segs.index("cxs")
            if len(segs) > i + 2:
                tenant, site = segs[i + 1], segs[i + 2]
        else:
            for s in segs:
                if _LOCALE_RE.match(s):
                    continue
                site = s
                break
        return {"host": host, "tenant": tenant, "site": site}

    if ats == "greenhouse":
        board = ""
        if "boards" in segs and "v1" in segs:
            i = segs.index("boards")
            board = segs[i + 1] if len(segs) > i + 1 else ""
        elif segs:
            board = segs[0]
        board = q.get("for", board)  # legacy embed URLs: ?for={board}
        return {"board": board}

    if ats == "lever":
        slug = ""
        if "postings" in segs:
            i = segs.index("postings")
            slug = segs[i + 1] if len(segs) > i + 1 else ""
        elif segs:
            slug = segs[0]
        return {"slug": slug}

    if ats == "smartrecruiters":
        company = ""
        if "companies" in segs:
            i = segs.index("companies")
            company = segs[i + 1] if len(segs) > i + 1 else ""
        elif segs:
            company = segs[0]
        return {"company": company}

    if ats == "eightfold":
        return {"host": host, "domain": q.get("domain", "")}

    if ats == "successfactors":
        # base = everything up to and including "/search/"
        path = parts.path
        base_path = path[: path.rfind("/search/") + len("/search/")] if "/search/" in path else path
        return {"base": urlunsplit((parts.scheme, host, base_path, "", ""))}

    if ats == "amazon_jobs":
        return {"host": host}

    return {"host": host}
