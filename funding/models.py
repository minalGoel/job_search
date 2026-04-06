from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class FundedCompany:
    """A recently funded startup."""
    company: str
    founder_ceo: str = ""
    founder_linkedin: str = ""
    industry: str = ""
    hq_location: str = ""
    delhi_ncr_office: str = ""  # "Yes (HQ)", "Yes (Dev Center)", "No", "Unknown"
    last_round_date: Optional[date] = None
    last_round_series: str = ""  # "Series A", "Series B", etc.
    amount_raised: str = ""  # "$15.6M", "₹30 Cr"
    source_url: str = ""  # Article URL
    work_mode: str = ""  # "In-office", "Hybrid", "Remote"
    linkedin_pm_roles: int = 0  # Count of open PM roles on LinkedIn
    linkedin_jobs_url: str = ""  # LinkedIn jobs search URL for this company
    careers_page: str = ""  # Company careers page URL

    @property
    def round_display(self) -> str:
        parts = []
        if self.last_round_date:
            parts.append(self.last_round_date.strftime("%b %d, %Y"))
        if self.last_round_series:
            parts.append(self.last_round_series)
        return " – ".join(parts)
