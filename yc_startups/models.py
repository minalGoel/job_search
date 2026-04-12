from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


def _yc_company_id(slug: str) -> str:
    """Deterministic ID from company slug."""
    return hashlib.sha256(f"yc|{slug}".encode()).hexdigest()[:16]


def _make_slug(name: str) -> str:
    """Normalise company name to a url-friendly slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


@dataclass
class YCCompany:
    """A Y Combinator portfolio company."""

    name: str
    slug: str = ""
    description: str = ""
    long_description: str = ""
    batch: str = ""
    website: str = ""
    hq_location: str = ""
    team_size: str = ""
    industry: str = ""
    subindustry: str = ""
    status: str = ""  # Active, Acquired, Inactive, Public
    logo_url: str = ""
    # Founder info embedded in the API payload
    founders: list[dict] = field(default_factory=list)
    # Hiring signals (populated later)
    is_hiring: bool = False
    is_hiring_pm: bool = False
    hiring_url: str = ""
    latest_hiring_check_at: str = ""
    last_refreshed_at: str = ""

    @property
    def id(self) -> str:
        return _yc_company_id(self.slug or _make_slug(self.name))

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = _make_slug(self.name)


@dataclass
class YCHiringSignal:
    """Evidence that a YC company is hiring."""

    company_id: str
    signal_type: str  # "yc_jobs_board", "wellfound", "careers_page", "work_at_startup"
    signal_source: str  # URL or platform name
    signal_date: str = ""
    signal_detail: str = ""  # Human-readable: "2 PM roles on Wellfound"
    checked_at: str = ""

    @property
    def id(self) -> str:
        raw = f"{self.company_id}|{self.signal_type}|{self.signal_date}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class YCFounderContact:
    """Enriched founder contact for a YC company."""

    yc_company_id: str
    founder_name: str
    founder_title: str = ""
    founder_email: str = ""
    founder_email_verified: bool = False
    founder_linkedin: str = ""
    founder_twitter: str = ""
    enrichment_source: str = ""  # "yc_api", "apollo", "prospeo"
    enriched_at: str = ""

    @property
    def id(self) -> str:
        raw = f"ycf|{self.yc_company_id}|{self.founder_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
