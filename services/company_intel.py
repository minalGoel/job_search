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
from typing import TYPE_CHECKING, Optional

from services.scoring import _company_slug

if TYPE_CHECKING:
    from storage.db import JobDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


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
    existing_profiles = db.get_all_company_profiles()

    def _get_or_create(slug: str, display_name: str) -> dict:
        if slug not in profiles:
            existing = existing_profiles.get(slug, {})
            profiles[slug] = {
                "normalized_company": slug,
                "company_display_name": existing.get("company_display_name") or display_name,
                "company_domain": existing.get("company_domain") or "",
                "is_mnc": int(existing.get("is_mnc", 0)),
                "is_funded": int(existing.get("is_funded", 0)),
                "funding_series": existing.get("funding_series"),
                "funding_amount": existing.get("funding_amount"),
                "funding_date": existing.get("funding_date"),
                "pm_open_roles_count": int(existing.get("pm_open_roles_count") or 0),
                "seen_platforms": list(existing.get("seen_platforms") or []),
                "careers_page": existing.get("careers_page"),
                "hq_location": existing.get("hq_location"),
                "hq_country": existing.get("hq_country") or "",
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
            p["hq_country"] = mnc.hq_country or p.get("hq_country") or ""
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
                p["company_domain"] = p.get("company_domain") or _extract_domain(vc.job_portal_url)
    except ImportError:
        pass

    # ----------------------------------------------------------------
    # 3. YC registry — mark portfolio companies as YC-backed
    # ----------------------------------------------------------------
    try:
        yc_companies = db.get_yc_companies()
        for yc in yc_companies:
            slug = _company_slug(yc.get("company_name", ""))
            if not slug:
                continue
            p = _get_or_create(slug, yc["company_name"])
            p["is_funded"] = 1
            p["is_yc_backed"] = 1
            p["yc_batch"] = yc.get("batch", "")
            if yc.get("website"):
                p["company_domain"] = p.get("company_domain") or _extract_domain(yc["website"])
            if yc.get("hq_location"):
                p["hq_location"] = p.get("hq_location") or yc["hq_location"]
    except Exception:
        pass  # Table may not exist on older DBs

    # ----------------------------------------------------------------
    # 4. Scraped jobs — aggregate PM role counts and seen platforms
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
    # 5. Persist
    # ----------------------------------------------------------------
    for profile in profiles.values():
        # Ensure seen_platforms is serialisable
        profile["seen_platforms"] = list(set(profile.get("seen_platforms") or []))
        db.upsert_company_profile(profile)

    return len(profiles)


def enrich_from_funding_data(db: "JobDB", output_dir: Optional[str] = None) -> int:
    """
    Cross-reference company_profiles with data from the most recent
    funded_companies_*.csv produced by the funding scanner.

    The funding scanner writes results to CSV (not to jobs.db), so this
    function reads the latest CSV from the output directory.

    Returns the number of profiles updated.
    """
    import csv
    from pathlib import Path

    if output_dir is None:
        output_dir = str(Path(__file__).resolve().parent.parent / "output")

    output_path = Path(output_dir)
    # Find the most recently written funding CSV
    csvs = sorted(output_path.glob("funded_companies_*.csv"), reverse=True)
    if not csvs:
        return 0

    latest_csv = csvs[0]
    updated = 0

    # CSV columns (from funding/exporter.py):
    # Company, Founder/CEO, Industry, HQ Location, Delhi NCR Office,
    # Last Round (Date & Series), Amt Raised, Source, Work Mode,
    # LinkedIn PM Roles, LinkedIn Jobs URL, Careers Page
    with open(latest_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company_name = (row.get("Company") or "").strip()
            if not company_name:
                continue

            slug = _company_slug(company_name)
            if not slug:
                continue

            round_text = _normalize(row.get("Last Round (Date & Series)") or "")
            funding_series: Optional[str] = None
            for series in ["series d", "series c", "series b", "series a", "pre-seed", "seed"]:
                if series in round_text:
                    funding_series = series.title()
                    break

            # Extract date portion (format: "Jan 01, 2024 – Series B")
            funding_date: Optional[str] = None
            import re as _re
            date_match = _re.search(r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", row.get("Last Round (Date & Series)") or "")
            if date_match:
                funding_date = date_match.group(1)

            profile = db.get_company_profile(slug)
            if not profile:
                profile = {
                    "normalized_company": slug,
                    "company_display_name": company_name,
                    "last_refreshed_at": datetime.now().isoformat(),
                }
            profile["is_funded"] = 1
            if funding_series:
                profile["funding_series"] = funding_series
            if funding_date:
                profile["funding_date"] = funding_date
            if row.get("Careers Page"):
                profile["careers_page"] = profile.get("careers_page") or row["Careers Page"].strip() or None
            if row.get("HQ Location"):
                profile["hq_location"] = profile.get("hq_location") or row["HQ Location"].strip()

            db.upsert_company_profile(profile)
            updated += 1

    return updated
