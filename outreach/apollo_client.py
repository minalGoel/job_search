from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from config.settings import Settings

log = structlog.get_logger(__name__)

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
ENRICH_URL = "https://api.apollo.io/api/v1/people/match"

PRODUCT_TITLES = [
    "Chief Product Officer", "VP Product", "Vice President Product",
    "Head of Product", "Director Product Management", "Director of Product",
    "Product Lead", "Senior Director Product",
]
FOUNDER_TITLES = ["CEO", "Founder", "Co-Founder", "CTO", "Managing Director"]
RECRUITER_TITLES = [
    "Talent Acquisition", "Recruiter", "Senior Recruiter",
    "HR Lead", "Head of Talent", "People Operations",
    "Hiring Manager",
]


class ApolloClient:
    """Apollo.io API client for People Search + Enrichment."""

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.APOLLO_API_KEY
        self.rate_limit = settings.APOLLO_RATE_LIMIT_PER_MINUTE
        self._request_count = 0
        self._last_call_ts: float = 0.0
        self._log = log.bind(client="apollo")

    async def search_contacts(
        self,
        company_name: str,
        title_keywords: list[str] | None = None,
        location: str = "India",
        per_page: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for people at a company by title.

        Returns list of person dicts with: id, first_name, last_name, title,
        organization, linkedin_url, etc. Does NOT include email.
        """
        if not self.api_key:
            self._log.warning("apollo.no_api_key")
            return []

        titles = title_keywords or (PRODUCT_TITLES + FOUNDER_TITLES + RECRUITER_TITLES)

        payload: dict[str, Any] = {
            "organization_names": [company_name],
            "person_titles": titles,
            "per_page": per_page,
        }
        if location:
            payload["person_locations"] = [location]

        await self._rate_limit()

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    SEARCH_URL,
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                people = data.get("people", [])
                self._log.info("apollo.search", company=company_name, results=len(people))
                return people
            except httpx.HTTPStatusError as e:
                self._log.error("apollo.search_error", status=e.response.status_code, company=company_name)
                return []
            except Exception:
                self._log.exception("apollo.search_failed", company=company_name)
                return []

    async def enrich_person(
        self,
        first_name: str,
        last_name: str,
        organization_name: str,
        linkedin_url: str = "",
    ) -> dict[str, Any] | None:
        """Enrich a person to get their verified email.

        Returns person dict with email, email_status, etc.
        """
        if not self.api_key:
            return None

        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "organization_name": organization_name,
            "reveal_personal_emails": True,
        }
        if linkedin_url:
            payload["linkedin_url"] = linkedin_url

        await self._rate_limit()

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    ENRICH_URL,
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                person = data.get("person")
                if person:
                    email = person.get("email", "")
                    status = person.get("email_status", "")
                    self._log.info(
                        "apollo.enrich",
                        name=f"{first_name} {last_name}",
                        email=email[:3] + "***" if email else "none",
                        status=status,
                    )
                return person
            except httpx.HTTPStatusError as e:
                self._log.error("apollo.enrich_error", status=e.response.status_code)
                return None
            except Exception:
                self._log.exception("apollo.enrich_failed")
                return None

    def classify_role(self, title: str) -> str:
        """Classify a person's title into product_leader, founder, or recruiter."""
        title_lower = title.lower()
        for kw in ["product", "pm "]:
            if kw in title_lower:
                return "product_leader"
        for kw in ["ceo", "founder", "co-founder", "cto", "managing director"]:
            if kw in title_lower:
                return "founder"
        for kw in ["recruit", "talent", "hr", "people", "hiring"]:
            if kw in title_lower:
                return "recruiter"
        return "other"

    async def _rate_limit(self) -> None:
        """Token-bucket style limiter: spaces calls by (60/rate_limit) seconds.

        Prevents the old bug where:
          1. rate_limit=0 crashed with ZeroDivisionError
          2. The "sleep 60 every Nth call" pattern let N calls burst back-to-back
        """
        self._request_count += 1
        if self.rate_limit is None or self.rate_limit <= 0:
            # Limiter disabled by config
            return

        # Minimum spacing between consecutive calls
        min_delay = 60.0 / float(self.rate_limit)

        loop = asyncio.get_event_loop()
        now = loop.time()
        if self._last_call_ts > 0.0:
            elapsed = now - self._last_call_ts
            if elapsed < min_delay:
                await asyncio.sleep(min_delay - elapsed)
        self._last_call_ts = loop.time()
