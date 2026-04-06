from __future__ import annotations

"""
Template-Based Outreach Writer (P1.2)

Generates ready-to-send recruiter / hiring-manager messages without LLM calls.

Process:
  1. Extract JD keywords from job title + description
  2. Map to candidate proof points from data/candidate_profile.json
  3. Select top 2-3 proof points
  4. Fill deterministic template

Templates:
  - recruiter      Short, warm intro to a recruiter
  - hiring-manager Slightly longer, more specific to the role
  - funded-startup Intro that references funding context
  - warm-intro     Request via a mutual connection
"""

import json
import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Profile loader
# ---------------------------------------------------------------------------

_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "candidate_profile.json"

_CACHED_PROFILE: Optional[dict] = None


def _load_profile() -> dict:
    global _CACHED_PROFILE
    if _CACHED_PROFILE is None:
        if _PROFILE_PATH.exists():
            with open(_PROFILE_PATH) as f:
                _CACHED_PROFILE = json.load(f)
        else:
            _CACHED_PROFILE = {}
    return _CACHED_PROFILE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# Keyword -> proof_point tag mapping
_KW_TO_TAG: list[tuple[str, str]] = [
    ("growth", "growth"),
    ("monetis", "monetisation"),
    ("monetiz", "monetisation"),
    ("pricing", "monetisation"),
    ("0-1", "0to1"),
    ("zero to one", "0to1"),
    ("platform", "platform"),
    ("api", "platform"),
    ("b2b", "b2b"),
    ("enterprise", "b2b"),
    ("saas", "b2b"),
    ("user research", "user_research"),
    ("discovery", "user_research"),
    ("analytics", "data"),
    ("data", "data"),
    ("okr", "data"),
    ("cross-functional", "cross_functional"),
    ("stakeholder", "cross_functional"),
]


def _pick_proof_points(job: dict, profile: dict, max_points: int = 3) -> list[str]:
    """Select the most relevant proof points for the job."""
    combined = _normalize(f"{job.get('title','')} {job.get('description','')}")
    tags_matched: list[str] = []
    for kw, tag in _KW_TO_TAG:
        if kw in combined and tag not in tags_matched:
            tags_matched.append(tag)

    proof_points = profile.get("proof_points", [])
    # Build tag -> text map
    tag_map: dict[str, str] = {pp["tag"]: pp["text"] for pp in proof_points if "tag" in pp and "text" in pp}

    selected: list[str] = []
    # First: matched tags
    for tag in tags_matched:
        if tag in tag_map and len(selected) < max_points:
            selected.append(tag_map[tag])
    # Fallback: any unselected proof points
    for pp in proof_points:
        if len(selected) >= max_points:
            break
        if pp.get("text") not in selected:
            selected.append(pp["text"])

    return selected[:max_points]


def _first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name else "there"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _template_recruiter(job: dict, profile: dict, contact_name: str = "") -> str:
    company = job.get("company", "your company")
    title = job.get("title", "Product Manager")
    years = profile.get("years_experience", "5+")
    strengths = ", ".join(profile.get("domain_strengths", ["B2B SaaS", "Growth"])[:3])
    points = _pick_proof_points(job, profile, max_points=2)
    bullet_lines = "\n".join(f"  • {p}" for p in points)
    greeting = f"Hi {_first_name(contact_name)}," if contact_name else "Hi,"

    return f"""{greeting}

I came across the {title} role at {company} and wanted to reach out — it looks like a strong match for my background.

I'm a PM with {years} years of experience specialising in {strengths}. A couple of highlights:

{bullet_lines}

I'd love to learn more about the role and what the team is building. Would you be open to a quick call?

Thanks,
{profile.get('headline', 'Senior Product Manager')}
{profile.get('linkedin_url', '')}""".strip()


def _template_hiring_manager(job: dict, profile: dict, contact_name: str = "", warm_note: str = "") -> str:
    company = job.get("company", "your company")
    title = job.get("title", "Product Manager")
    years = profile.get("years_experience", "5+")
    points = _pick_proof_points(job, profile, max_points=3)
    bullet_lines = "\n".join(f"  • {p}" for p in points)
    greeting = f"Hi {_first_name(contact_name)}," if contact_name else "Hi,"
    warm_line = f"\n{warm_note}\n" if warm_note else ""

    return f"""{greeting}
{warm_line}
I noticed the {title} opening at {company} and wanted to reach out directly.

I've spent {years} years building products at the intersection of {', '.join(job_industries(job))} — and the challenges you're likely solving resonate closely with work I've shipped.

A few things that might be relevant:
{bullet_lines}

I'd welcome a 20-minute conversation to explore if there's a fit. Happy to share specific examples or a case study.

Best,
{profile.get('headline', 'Senior Product Manager')}
{profile.get('linkedin_url', '')}""".strip()


def _template_funded_startup(job: dict, profile: dict, contact_name: str = "", funding_context: str = "") -> str:
    company = job.get("company", "your company")
    title = job.get("title", "Product Manager")
    years = profile.get("years_experience", "5+")
    points = _pick_proof_points(job, profile, max_points=2)
    bullet_lines = "\n".join(f"  • {p}" for p in points)
    greeting = f"Hi {_first_name(contact_name)}," if contact_name else "Hi,"
    funding_line = f"Congrats on {funding_context} — exciting time to build!" if funding_context else f"Congrats on {company}'s recent growth!"

    return f"""{greeting}

{funding_line} I came across the {title} role and it looks like a compelling fit.

I'm a PM with {years} years of experience who's worked in fast-scaling product environments. Two things I'd bring to your stage:

{bullet_lines}

Happy to have a quick call if the timing is right.

Best,
{profile.get('headline', 'Senior Product Manager')}
{profile.get('linkedin_url', '')}""".strip()


def _template_warm_intro(job: dict, profile: dict, mutual_name: str, contact_name: str = "") -> str:
    company = job.get("company", "your company")
    title = job.get("title", "Product Manager")
    greeting = f"Hi {_first_name(contact_name)}," if contact_name else "Hi,"

    return f"""{greeting}

{mutual_name} suggested I reach out — I'm exploring PM roles and the {title} position at {company} caught my attention.

I'd love to learn more about the team and the problem space. Would you have 15 minutes for a quick chat?

Thanks,
{profile.get('headline', 'Senior Product Manager')}
{profile.get('linkedin_url', '')}""".strip()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def job_industries(job: dict) -> list[str]:
    """Guess relevant industries from job title + description for template text."""
    combined = _normalize(f"{job.get('title', '')} {job.get('description', '')}")
    tags = []
    checks = [
        ("fintech", "fintech"), ("edtech", "edtech"), ("saas", "SaaS"),
        ("b2b", "B2B"), ("marketplace", "marketplace"), ("api", "developer tools"),
        ("platform", "platform products"), ("growth", "growth"),
    ]
    for kw, label in checks:
        if kw in combined:
            tags.append(label)
    return tags[:3] if tags else ["product"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def draft_message(
    job: dict,
    message_type: str = "recruiter",
    contact_name: str = "",
    mutual_name: str = "",
    funding_context: str = "",
    warm_note: str = "",
) -> str:
    """
    Generate a draft outreach message for a job dict.

    Args:
        job: job dict from DB
        message_type: 'recruiter' | 'hiring-manager' | 'funded-startup' | 'warm-intro'
        contact_name: name of recipient (optional)
        mutual_name: mutual connection name (for warm-intro only)
        funding_context: e.g. 'Series B' (for funded-startup template)
        warm_note: custom warm context sentence (for hiring-manager)

    Returns:
        Draft message as plain text string.
    """
    profile = _load_profile()

    if message_type == "recruiter":
        return _template_recruiter(job, profile, contact_name)
    elif message_type == "hiring-manager":
        return _template_hiring_manager(job, profile, contact_name, warm_note)
    elif message_type == "funded-startup":
        return _template_funded_startup(job, profile, contact_name, funding_context)
    elif message_type == "warm-intro":
        if not mutual_name:
            mutual_name = "a mutual connection"
        return _template_warm_intro(job, profile, mutual_name, contact_name)
    else:
        raise ValueError(
            f"Unknown message_type '{message_type}'. "
            "Use: recruiter | hiring-manager | funded-startup | warm-intro"
        )
