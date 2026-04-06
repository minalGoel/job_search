from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class OutreachContact(BaseModel):
    """A person at a target company to reach out to."""

    id: str = ""
    company: str
    company_domain: str = ""
    contact_name: str = ""
    contact_title: str = ""
    contact_email: str = ""
    contact_email_status: str = ""  # "verified", "guessed", "unavailable"
    contact_linkedin: str = ""
    contact_role_type: str = ""  # "product_leader", "recruiter", "founder"
    source: str = ""  # "job_listing", "funding_scanner", "both"
    source_job_id: str = ""
    source_job_title: str = ""
    source_job_link: str = ""
    funding_amount: str = ""
    funding_series: str = ""
    funding_date: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    status: str = "new"

    @model_validator(mode="after")
    def _compute_id(self) -> OutreachContact:
        if not self.id:
            raw = f"{self.company}|{self.contact_email or self.contact_name}|{self.contact_title}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self


class OutreachEmail(BaseModel):
    """A single email in an outreach sequence."""

    id: str = ""
    contact_id: str
    sequence_step: int = 1  # 1=intro, 2=follow-up day 3, 3=final day 7
    subject: str = ""
    body_html: str = ""
    body_plain: str = ""
    template_name: str = ""
    scheduled_send_at: Optional[datetime] = None
    actual_sent_at: Optional[datetime] = None
    status: str = "draft"  # "draft", "approved", "sent", "bounced", "replied", "skipped", "snoozed"
    gmail_message_id: str = ""
    gmail_thread_id: str = ""

    @model_validator(mode="after")
    def _compute_id(self) -> OutreachEmail:
        if not self.id:
            raw = f"{self.contact_id}|{self.sequence_step}|{self.subject}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self
