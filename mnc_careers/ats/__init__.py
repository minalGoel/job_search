"""Typed ATS fetchers — fetch the *full* listing, filter locally later.

``FETCHERS`` maps an ``api_type`` / detected ATS to its ``fetch_all``
coroutine. Anything not in this map goes through the Playwright HTML lane
(``mnc_careers/html_generic.py``).
"""
from __future__ import annotations

from mnc_careers.ats import amazon_jobs, avature, eightfold, greenhouse, lever, oracle_hcm, phenom, radancy, smartrecruiters, successfactors, workday
from mnc_careers.ats.base import FetchError, FetchResult, NotThisATS, RawPosting
from mnc_careers.ats.detect import HTML_ONLY, TYPED, detect_ats, parse_target, strip_search_params

FETCHERS = {
    "workday": workday.fetch_all,
    "greenhouse": greenhouse.fetch_all,
    "lever": lever.fetch_all,
    "smartrecruiters": smartrecruiters.fetch_all,
    "successfactors": successfactors.fetch_all,
    "amazon_jobs": amazon_jobs.fetch_all,
    "phenom": phenom.fetch_all,
    "oracle_hcm": oracle_hcm.fetch_all,
    "radancy": radancy.fetch_all,
    "avature": avature.fetch_all,
    # Eightfold's public API answers 403 "Not authorized for PCSX" to non-browser
    # callers, so detected "eightfold" sites go through the HTML lane (whose JSON
    # interception captures the same /api/apply/v2/jobs response with the browser
    # session). Use api_type="eightfold_api" explicitly for tenants whose API is open.
    "eightfold_api": eightfold.fetch_all,
}

__all__ = [
    "FETCHERS",
    "FetchError",
    "FetchResult",
    "NotThisATS",
    "RawPosting",
    "HTML_ONLY",
    "TYPED",
    "detect_ats",
    "parse_target",
    "strip_search_params",
]
