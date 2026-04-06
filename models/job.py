from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


def _normalize(text: str) -> str:
    """Lowercase, strip whitespace, collapse spaces."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _strip_company_suffixes(name: str) -> str:
    """Remove common legal suffixes for dedup matching."""
    suffixes = [
        "pvt", "ltd", "limited", "private", "inc", "incorporated",
        "corp", "corporation", "llc", "technologies", "technology",
        "software", "solutions", "india", "services", "labs",
    ]
    words = _normalize(name).split()
    return " ".join(w for w in words if w not in suffixes)


def _strip_title_decorators(title: str) -> str:
    """Remove location/mode suffixes like '- Remote', '- Hybrid'."""
    cleaned = re.sub(r"\s*[-–—|]\s*(remote|hybrid|onsite|on-site|wfh|work from home|delhi|ncr|gurugram|gurgaon|noida).*$", "", title, flags=re.IGNORECASE)
    return _normalize(cleaned)


class Job(BaseModel):
    id: str = ""
    platform: str
    title: str
    company: str
    location: str
    salary: Optional[str] = None
    posted_date: Optional[date] = None
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    apply_link: str
    scraped_at: datetime = Field(default_factory=datetime.now)
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None

    @model_validator(mode="after")
    def _compute_id(self) -> "Job":
        if not self.id:
            raw = f"{self.platform}|{_normalize(self.company)}|{_normalize(self.title)}|{self.apply_link}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self

    @property
    def dedup_hash(self) -> str:
        """Cross-platform dedup key: normalized company + title."""
        company = _strip_company_suffixes(self.company)
        title = _strip_title_decorators(self.title)
        raw = f"{company}|{title}|delhi"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
