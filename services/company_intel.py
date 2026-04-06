from __future__ import annotations

"""
Company Intelligence Cache (P0.4)

Builds and refreshes the company_profiles table using only local / project data:
  - MNC registry (mnc_careers/registry.py)
  - VC registry  (vc_portals/registry.py)
  - Funding scan results already in jobs DB
  - Scraped jobs grouped by normalised company

No paid APIs are used in this module.
"""

import re
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.db import JobDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _company_slug(name: str) -> str:
    """Normalised slug: remove punctuation, common legal suffixes."""
    s = re.sub(r"[^a-z0-9 ]", "", _normalize(name))
    suffixes = {
        "pvt", "ltd", "limited", "private", "inc", "incorporated",
        "corp", "corporation", "llc", "technologies", "technology",
        "software", "solutions", "india", "services", "labs", "ventures",
    }
    words = [w for w in s.split() if w not in suffixes]
    return " ".join(words).strip()


def _extract_domain(url: str) -> str:
    """Best-effort domain extraction from a careers page URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc or parsed.path
        host = re.sub(r"^www\.", "", host)
        return host.split("/")[0]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def build_company_profiles(db: "JobDB") -> int:
    """
    Rebuild company_profiles from local data sources.
    Returns the number of profiles upserted.
    """
    profiles: dict[str, dict] = {}

    def _get_or_create(slug: str, display_name: str) -> dict:
        if slug not in profiles:
            profiles[slug] = {
                "normalized_company": slug,
                "company_display_name": display_name,
                "company_domain": "",
                "is_mnc": 0,
                "is_funded": 0,
                "funding_series": None,
                "funding_amount": None,
                "funding_date": None,
                "pm_open_roles_count": 0,
                "seen_platforms": [],
                "careers_page": None,
                "hq_location": None,
                "last_refreshed_at": datetime.now().isoformat(),
            }
        return profiles[slug]

    # ----------------------------------------------------------------
    # 1. MNC registry
    # ----------------------------------------------------------------
    try:
        from mnc_careers.registry import MNC_REGISTRY
        for mnc in MNC_REGISTRY:
            slug = _company_slug(mnc.name)
            p = _get_or_create(slug, mnc.name)
            p["is_mnc"] = 1
            p["hq_location"] = mnc.delhi_ncr_office or p.get("hq_location")
            p["careers_page"] = mnc.careers_url or p.get("careers_page")
            if mnc.careers_url:
                p["company_domain"] = _extract_domain(mnc.careers_url)
    except ImportError:
        pass

    # ----------------------------------------------------------------
    # 2. VC registry — mark portfolio companies as VC-backed
    # ----------------------------------------------------------------
    try:
        from vc_portals.registry import VC_REGISTRY
        for vc in VC_REGISTRY:
            if vc.job_portal_url:
                slug = _company_slug(vc.name)
                p = _get_or_create(slug, vc.name)
                p["careers_page"] = p.get("careers_page") or vc.job_portal_url
    except ImportError:
        pass

    # ----------------------------------------------------------------
    # 3. Scraped jobs — aggregate PM role counts and seen platforms
    # ----------------------------------------------------------------
    all_jobs = db.get_all_jobs()
    company_jobs: dict[str, list[dict]] = {}
    for job in all_jobs:
        if job.get("is_duplicate"):
            continue
        slug = _company_slug(job.get("company", ""))
        if not slug:
            continue
        company_jobs.setdefault(slug, []).append(job)

    for slug, jobs in company_jobs.items():
        display = jobs[0].get("company", slug)
        p = _get_or_create(slug, display)
        p["pm_open_roles_count"] = len(jobs)
        platforms = list({j.get("platform", "") for j in jobs if j.get("platform")})
        p["seen_platforms"] = list(set(p.get("seen_platforms", []) + platforms))

        # Try to grab a careers page from apply_link if it looks like an ATS
        for job in jobs:
            link = job.get("apply_link", "")
            domain = _extract_domain(link)
            if domain and not p.get("company_domain"):
                p["company_domain"] = domain
            # Prefer direct careers / ATS links
            ats_hints = ["greenhouse.io", "lever.co", "workday.com", "smartrecruiters", "myworkdayjobs"]
            if any(hint in link for hint in ats_hints) and not p.get("careers_page"):
                p["careers_page"] = link

    # ----------------------------------------------------------------
    # 4. Persist
    # ----------------------------------------------------------------
    for profile in profiles.values():
        # Ensure seen_platforms is serialisable
        profile["seen_platforms"] = list(set(profile.get("seen_platforms") or []))
        db.upsert_company_profile(profile)

    return len(profiles)


def enrich_from_funding_data(db: "JobDB") -> int:
    """
    Cross-reference company_profiles with funding info stored as jobs
    from the funding scanner (platform = 'funding_scanner').
    Returns the number of profiles updated.
    """
    updated = 0
    all_jobs = db.get_all_jobs()
    funding_jobs = [j for j in all_jobs if j.get("platform") == "funding_scanner"]

    for fjob in funding_jobs:
        slug = _company_slug(fjob.get("company", ""))
        if not slug:
            continue
        profile = db.get_company_profile(slug)
        if not profile:
            profile = {
                "normalized_company": slug,
                "company_display_name": fjob.get("company", ""),
                "is_funded": 1,
                "last_refreshed_at": datetime.now().isoformat(),
            }
        else:
            profile["is_funded"] = 1

        # Try to extract series from salary field (funding scanner stores amount there)
        salary_text = _normalize(fjob.get("salary") or "")
        for series in ["series d", "series c", "series b", "series a", "seed", "pre-seed"]:
            if series in salary_text or series in _normalize(fjob.get("description") or ""):
                profile["funding_series"] = series.title()
                break

        if fjob.get("posted_date"):
            profile["funding_date"] = str(fjob["posted_date"])

        db.upsert_company_profile(profile)
        updated += 1

    return updated
