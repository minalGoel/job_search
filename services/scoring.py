from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from config.scoring_rules import (
    AGENCY_KEYWORDS,
    BUCKET_THRESHOLDS,
    COMPANY_QUALITY_SCORES,
    DIRECT_SOURCE_PLATFORMS,
    HIGH_PAYING_COMPANIES,
    HIGH_PAYING_COMPANY_SCORE,
    LOCATION_ALLOWLIST,
    LOCATION_MATCH_SCORE,
    LOCATION_MISMATCH_SCORE,
    NEGATIVE_KEYWORD_SCORE,
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORD_CAP,
    POSITIVE_KEYWORD_SCORE,
    POSITIVE_KEYWORDS,
    PRIORITY_WEIGHTS,
    RECENCY_BONUSES,
    SALARY_SCORES,
    TITLE_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _company_slug(name: str) -> str:
    """Remove punctuation + legal suffixes, return lowercase slug."""
    s = re.sub(r"[^a-z0-9 ]", "", _normalize(name))
    return re.sub(r"\s+", " ", s).strip()


def _priority_bucket(score: int) -> str:
    for bucket, threshold in BUCKET_THRESHOLDS:
        if score >= threshold:
            return bucket
    return "low"


def _days_old(posted_date: Optional[str | date]) -> Optional[int]:
    if not posted_date:
        return None
    try:
        if isinstance(posted_date, str):
            pd = date.fromisoformat(posted_date)
        else:
            pd = posted_date
        return (date.today() - pd).days
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

def score_job(job: dict, company_profile: Optional[dict] = None) -> dict:
    """
    Score a single job dict.

    Returns a dict with:
        relevance_score         int  0-100
        salary_likelihood_score int  0-100
        warmth_score            int  0-100  (0 until connection data imported)
        company_quality_score   int  0-100
        priority_score          int  0-100
        priority_bucket         str  must_apply | high | medium | low
        score_reasons           str  JSON list of positive signal tags
        priority_flags          str  JSON list of negative / warning tags
    """
    title = _normalize(job.get("title", ""))
    description = _normalize(job.get("description", ""))
    location = _normalize(job.get("location", ""))
    platform = _normalize(job.get("platform", ""))
    posted_date = job.get("posted_date")
    existing_warmth = int(job.get("warmth_score") or 0)

    reasons: list[str] = []
    flags: list[str] = []

    # ----------------------------------------------------------------
    # 1. Relevance score
    # ----------------------------------------------------------------
    relevance = 0

    # Title weights — first matching rule wins
    for pattern, weight in TITLE_WEIGHTS:
        if pattern in title:
            tag = pattern.replace(" ", "_")
            if weight > 0:
                reasons.append(tag)
            else:
                flags.append(tag)
            relevance += weight
            break

    # Positive domain keywords (capped)
    combined = f"{title} {description}"
    keyword_bonus = 0
    matched_kw: list[str] = []
    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            keyword_bonus += POSITIVE_KEYWORD_SCORE
            matched_kw.append(kw)
    keyword_bonus = min(keyword_bonus, POSITIVE_KEYWORD_CAP)
    relevance += keyword_bonus
    if matched_kw:
        reasons.append(f"keywords:{','.join(matched_kw[:3])}")

    # Negative keywords
    neg_matched: list[str] = []
    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            relevance += NEGATIVE_KEYWORD_SCORE
            neg_matched.append(kw)
    if neg_matched:
        flags.append(f"negative_keywords:{','.join(neg_matched[:2])}")

    # Location
    loc_match = any(allowed in location for allowed in LOCATION_ALLOWLIST)
    if loc_match:
        relevance += LOCATION_MATCH_SCORE
        reasons.append("location_match")
    elif location:
        relevance += LOCATION_MISMATCH_SCORE
        flags.append("non_target_location")

    # Recency
    age = _days_old(posted_date)
    if age is not None:
        for max_age, bonus in RECENCY_BONUSES:
            if age <= max_age:
                relevance += bonus
                if bonus > 0:
                    reasons.append(f"recent_{age}d")
                elif bonus < 0:
                    flags.append("stale_posting")
                break

    # Direct platform source
    is_direct = platform in DIRECT_SOURCE_PLATFORMS
    if is_direct:
        relevance += 10
        reasons.append("direct_source")

    relevance = max(0, min(100, relevance))

    # ----------------------------------------------------------------
    # 2. Salary likelihood score
    # ----------------------------------------------------------------
    salary = 0

    company_slug = _company_slug(job.get("company", ""))
    if any(hpc in company_slug for hpc in HIGH_PAYING_COMPANIES):
        salary += HIGH_PAYING_COMPANY_SCORE
        reasons.append("high_paying_company")

    if company_profile:
        if company_profile.get("is_mnc"):
            salary += SALARY_SCORES["mnc"]
            reasons.append("mnc_company")
        if company_profile.get("is_funded"):
            series = _normalize(company_profile.get("funding_series") or "")
            if any(s in series for s in ["series c", "series d", "series e", "late stage"]):
                salary += SALARY_SCORES["series_c_plus"]
                reasons.append("series_c_plus")
            elif "series b" in series:
                salary += SALARY_SCORES["series_b"]
                reasons.append("series_b")
            elif "series a" in series:
                salary += SALARY_SCORES["series_a"]
                reasons.append("series_a")
            else:
                salary += SALARY_SCORES["seed"]
                reasons.append("funded_company")

    # Seniority bonus for salary
    if any(kw in title for kw in ["senior", "lead", "group", "principal", "head of", "director"]):
        salary += SALARY_SCORES["senior_pm_title"]
        reasons.append("senior_title")
    elif " ii" in title or " 2 " in title or "pm2" in title:
        salary += SALARY_SCORES["pm_ii_title"]

    if is_direct:
        salary += SALARY_SCORES["direct_source"]

    salary = max(0, min(100, salary))

    # ----------------------------------------------------------------
    # 3. Warmth score — pre-populated from connection matching
    # ----------------------------------------------------------------
    warmth = existing_warmth

    # ----------------------------------------------------------------
    # 4. Company quality score
    # ----------------------------------------------------------------
    quality = 0

    if company_profile:
        if company_profile.get("is_mnc"):
            quality += COMPANY_QUALITY_SCORES["mnc"]
        if company_profile.get("is_funded"):
            quality += COMPANY_QUALITY_SCORES["recent_funding"]
            reasons.append("funded_company_quality")
        pm_count = int(company_profile.get("pm_open_roles_count") or 0)
        if pm_count >= 2:
            quality += COMPANY_QUALITY_SCORES["multiple_pm_roles"]
            reasons.append(f"{pm_count}_pm_openings")
        if company_profile.get("careers_page"):
            quality += COMPANY_QUALITY_SCORES["direct_source"]

    if is_direct:
        quality += COMPANY_QUALITY_SCORES["direct_source"]

    quality = max(0, min(100, quality))

    # ----------------------------------------------------------------
    # 5. Priority score (weighted composite)
    # ----------------------------------------------------------------
    priority = int(
        relevance * PRIORITY_WEIGHTS["relevance"]
        + salary * PRIORITY_WEIGHTS["salary"]
        + warmth * PRIORITY_WEIGHTS["warmth"]
        + quality * PRIORITY_WEIGHTS["company_quality"]
    )
    priority = max(0, min(100, priority))
    bucket = _priority_bucket(priority)

    # ----------------------------------------------------------------
    # 6. Additional flags
    # ----------------------------------------------------------------
    if "project manager" in title and "product" not in title:
        flags.append("likely_project_manager_role")
    if any(kw in title for kw in ["associate", "intern", "trainee", "junior", "entry level"]):
        flags.append("junior_seniority")
    if age is not None and age > 30:
        if "stale_posting" not in flags:
            flags.append("stale_posting")

    company_lower = _company_slug(job.get("company", ""))
    if any(kw in company_lower for kw in AGENCY_KEYWORDS):
        flags.append("agency_or_staffing_company")

    if loc_match and "remote" in location:
        reasons.append("remote_friendly")

    # Deduplicate while preserving order
    reasons = list(dict.fromkeys(reasons))
    flags = list(dict.fromkeys(flags))

    return {
        "relevance_score": relevance,
        "salary_likelihood_score": salary,
        "warmth_score": warmth,
        "company_quality_score": quality,
        "priority_score": priority,
        "priority_bucket": bucket,
        "score_reasons": json.dumps(reasons),
        "priority_flags": json.dumps(flags),
    }


def score_jobs(
    jobs: list[dict],
    company_profiles: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """
    Score a list of job dicts.

    company_profiles maps company_slug -> profile dict (from company_intel).
    Returns new list with score fields merged in.
    """
    company_profiles = company_profiles or {}
    result = []
    for job in jobs:
        slug = _company_slug(job.get("company", ""))
        profile = company_profiles.get(slug)
        scores = score_job(job, profile)
        result.append({**job, **scores})
    return result
