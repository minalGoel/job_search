from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from config.settings import Settings
from outreach.apollo_client import ApolloClient
from outreach.db import OutreachDB
from outreach.models import OutreachContact
from outreach.prospeo_client import ProspeoClient
from services.scoring import _company_slug

log = structlog.get_logger(__name__)

# Priority order for contact search by estimated company size
TITLE_TIERS_STARTUP = ["founder", "product_leader", "recruiter"]
TITLE_TIERS_MIDSIZE = ["product_leader", "recruiter", "founder"]
TITLE_TIERS_ENTERPRISE = ["recruiter", "product_leader"]


class OutreachEnricher:
    """Orchestrates: company → find contacts (Apollo) → get emails → store."""

    def __init__(self, settings: Settings, db: OutreachDB) -> None:
        self.settings = settings
        self.db = db
        self.apollo = ApolloClient(settings)
        self.prospeo = ProspeoClient(settings)
        self._log = log.bind(module="enricher")

    async def enrich_from_jobs(self, job_dicts: list[dict]) -> int:
        """Process new job listings into outreach contacts.

        Groups by company (one outreach per company), skips companies
        already in the pipeline.
        """
        # Deduplicate by company
        companies: dict[str, dict] = {}
        for job in job_dicts:
            company = job.get("company", "").strip()
            if not company:
                continue
            key = _company_slug(company)
            if key not in companies:
                companies[key] = job

        self._log.info("enrich.jobs", unique_companies=len(companies))
        count = 0

        for key, job in companies.items():
            company = job["company"]

            # Skip if already in pipeline
            if self.db.company_has_outreach(company):
                self._log.debug("enrich.skip_existing", company=company)
                continue

            contacts = await self._find_and_enrich_contacts(
                company=company,
                source="job_listing",
                source_job_id=job.get("id", ""),
                source_job_title=job.get("title", ""),
                source_job_link=job.get("apply_link", ""),
            )
            count += contacts
            await asyncio.sleep(self.settings.APOLLO_RATE_LIMIT_PER_MINUTE / 10)

        return count

    async def enrich_from_funding(self, funded_companies: list[dict]) -> int:
        """Process funded companies into outreach contacts."""
        self._log.info("enrich.funding", companies=len(funded_companies))
        count = 0

        for fc in funded_companies:
            company = fc.get("company", "").strip()
            if not company:
                continue

            if self.db.company_has_outreach(company):
                self._log.debug("enrich.skip_existing", company=company)
                continue

            contacts = await self._find_and_enrich_contacts(
                company=company,
                source="funding_scanner",
                funding_amount=fc.get("amount_raised", ""),
                funding_series=fc.get("last_round_series", ""),
                funding_date=fc.get("last_round_date", ""),
            )
            count += contacts
            await asyncio.sleep(self.settings.APOLLO_RATE_LIMIT_PER_MINUTE / 10)

        return count

    async def _find_and_enrich_contacts(
        self,
        company: str,
        source: str,
        source_job_id: str = "",
        source_job_title: str = "",
        source_job_link: str = "",
        funding_amount: str = "",
        funding_series: str = "",
        funding_date: str = "",
    ) -> int:
        """Find contacts at a company and enrich with verified emails."""
        # Step 1: Apollo People Search
        people = await self.apollo.search_contacts(company)
        if not people:
            self._log.info("enrich.no_contacts", company=company)
            return 0

        # Classify and prioritize
        classified: dict[str, list[dict]] = {"product_leader": [], "founder": [], "recruiter": [], "other": []}
        for person in people:
            title = person.get("title", "")
            role_type = self.apollo.classify_role(title)
            classified[role_type].append(person)

        # Estimate company size from Apollo org data
        org = people[0].get("organization", {}) if people else {}
        employee_count = org.get("estimated_num_employees", 0) or 0
        company_domain = org.get("primary_domain", "") or ""

        if employee_count < 100:
            tier_order = TITLE_TIERS_STARTUP
        elif employee_count < 500:
            tier_order = TITLE_TIERS_MIDSIZE
        else:
            tier_order = TITLE_TIERS_ENTERPRISE

        # Pick best contact (1 per company — one-per-company rule)
        selected: list[dict] = []
        for tier in tier_order:
            for person in classified.get(tier, []):
                if len(selected) >= 1:
                    break
                selected.append({**person, "_role_type": tier})
            if len(selected) >= 1:
                break

        if not selected:
            self._log.info("enrich.no_matching_roles", company=company)
            return 0

        # Step 2: Enrich each selected contact with email
        enriched_count = 0
        for person in selected:
            first_name = person.get("first_name", "")
            last_name = person.get("last_name", "")
            title = person.get("title", "")
            linkedin_url = person.get("linkedin_url", "")
            role_type = person.get("_role_type", "other")

            # Apollo enrich
            enriched = await self.apollo.enrich_person(
                first_name, last_name, company, linkedin_url
            )
            self.db.log_credit("apollo", "enrich")

            email = ""
            email_status = "unavailable"

            if enriched:
                email = enriched.get("email", "") or ""
                email_status = enriched.get("email_status", "unavailable") or "unavailable"

            # Prospeo fallback if Apollo didn't find email
            if not email and self.prospeo.api_key:
                self._log.info("enrich.prospeo_fallback", name=f"{first_name} {last_name}")
                prospeo_result = await self.prospeo.enrich_person(
                    first_name, last_name, company_domain, linkedin_url
                )
                self.db.log_credit("prospeo", "enrich")
                if prospeo_result and prospeo_result.get("email"):
                    email = prospeo_result["email"]
                    email_status = "verified" if prospeo_result.get("confidence", 0) > 80 else "guessed"

            # Create and store contact
            contact = OutreachContact(
                company=company,
                company_domain=company_domain,
                contact_name=f"{first_name} {last_name}".strip(),
                contact_title=title,
                contact_email=email,
                contact_email_status=email_status,
                contact_linkedin=linkedin_url,
                contact_role_type=role_type,
                source=source,
                source_job_id=source_job_id,
                source_job_title=source_job_title,
                source_job_link=source_job_link,
                funding_amount=funding_amount,
                funding_series=funding_series,
                funding_date=str(funding_date) if funding_date else "",
                status="enriched" if email else "new",
            )

            if self.db.insert_contact(contact):
                enriched_count += 1
                self._log.info(
                    "enrich.contact_stored",
                    company=company,
                    name=contact.contact_name,
                    role=role_type,
                    has_email=bool(email),
                )

        self.db.log_credit("apollo", "search")
        return enriched_count
