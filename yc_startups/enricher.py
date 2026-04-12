"""
yc_startups/enricher.py — Enrich YC founder contacts via Apollo.

Two-step flow (same as outreach/enricher.py):
  1. Apollo People Search — find founders by company name + title
  2. Apollo People Enrich — get verified email for each founder

Founders already stored from the YC API get enriched first (cheaper —
we already have their name + company). Unknown founders are discovered
via the search step.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import structlog

from config.settings import Settings
from outreach.apollo_client import ApolloClient, FOUNDER_TITLES
from yc_startups.models import YCFounderContact

log = structlog.get_logger(__name__)


async def enrich_yc_founders(
    companies: list[dict],
    settings: Settings,
    limit: int = 50,
    dry_run: bool = False,
) -> list[dict]:
    """Enrich founder contacts for a list of YC companies.

    Args:
        companies: Company dicts from yc_companies table (must include
                   'id', 'company_name', 'founders' JSON).
        settings: App settings (needs APOLLO_API_KEY).
        limit: Max companies to enrich (to control Apollo credit usage).
        dry_run: If True, log what would be enriched without calling Apollo.

    Returns:
        List of enriched founder dicts ready for DB insertion.
    """
    if not settings.APOLLO_API_KEY:
        log.warning("yc.enrich.no_apollo_key")
        return []

    client = ApolloClient(settings)
    enriched: list[dict] = []
    companies_to_enrich = companies[:limit]

    log.info("yc.enrich.start", companies=len(companies_to_enrich), dry_run=dry_run)

    for company in companies_to_enrich:
        company_id = company["id"]
        company_name = company.get("company_name") or company.get("name", "")
        if not company_name:
            continue

        # Parse existing founders from YC API data
        known_founders = _parse_founders_json(company.get("founders", "[]"))

        if dry_run:
            log.info("yc.enrich.dry_run", company=company_name, founders=len(known_founders))
            continue

        try:
            founders = await _enrich_company_founders(
                client, company_id, company_name, known_founders,
            )
            enriched.extend(founders)
        except Exception:
            log.exception("yc.enrich.company_failed", company=company_name)

    log.info(
        "yc.enrich.done",
        total=len(enriched),
        verified=sum(1 for e in enriched if e.get("founder_email_verified")),
    )
    return enriched


async def _enrich_company_founders(
    client: ApolloClient,
    company_id: str,
    company_name: str,
    known_founders: list[dict],
) -> list[dict]:
    """Enrich founders for a single company."""
    results: list[dict] = []
    now = datetime.now().isoformat()

    if known_founders:
        # Path A: We have founder names from YC API — go straight to Enrich
        for founder in known_founders:
            name = founder.get("name", "").strip()
            if not name:
                continue
            parts = name.split(None, 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ""

            person = await client.enrich_person(
                first_name=first,
                last_name=last,
                organization_name=company_name,
                linkedin_url=founder.get("linkedin", ""),
            )

            contact = _build_contact(
                company_id, name, founder.get("title", "Founder"),
                person, founder, now,
            )
            results.append(contact)
    else:
        # Path B: No known founders — use Apollo People Search first
        people = await client.search_contacts(
            company_name=company_name,
            title_keywords=FOUNDER_TITLES,
            location="",  # Don't filter by location for founders
            per_page=5,
        )

        for person_stub in people:
            first = person_stub.get("first_name", "")
            last = person_stub.get("last_name", "")
            title = person_stub.get("title", "")
            if not first:
                continue

            # Enrich to get email
            person = await client.enrich_person(
                first_name=first,
                last_name=last,
                organization_name=company_name,
                linkedin_url=person_stub.get("linkedin_url", ""),
            )

            contact = _build_contact(
                company_id, f"{first} {last}", title,
                person, person_stub, now,
            )
            results.append(contact)

    return results


def _build_contact(
    company_id: str,
    name: str,
    title: str,
    enriched_person: dict | None,
    source_data: dict,
    now: str,
) -> dict:
    """Build a founder contact dict from enrichment results."""
    email = ""
    email_verified = False
    linkedin = source_data.get("linkedin") or source_data.get("linkedin_url", "")
    twitter = source_data.get("twitter") or source_data.get("twitter_url", "")

    if enriched_person:
        email = enriched_person.get("email", "") or ""
        email_verified = enriched_person.get("email_status") == "verified"
        linkedin = linkedin or enriched_person.get("linkedin_url", "")
        twitter = twitter or enriched_person.get("twitter_url", "")
        title = title or enriched_person.get("title", "")

    fc = YCFounderContact(
        yc_company_id=company_id,
        founder_name=name,
        founder_title=title,
        founder_email=email,
        founder_email_verified=email_verified,
        founder_linkedin=linkedin,
        founder_twitter=twitter,
        enrichment_source="apollo" if enriched_person else "yc_api",
        enriched_at=now,
    )

    return {
        "id": fc.id,
        "yc_company_id": company_id,
        "founder_name": name,
        "founder_title": title,
        "founder_email": email,
        "founder_email_verified": int(email_verified),
        "founder_linkedin": linkedin,
        "founder_twitter": twitter,
        "enrichment_source": fc.enrichment_source,
        "enriched_at": now,
    }


def _parse_founders_json(raw: str | list) -> list[dict]:
    """Parse founders JSON safely."""
    if isinstance(raw, list):
        return raw
    if not raw or raw == "[]":
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
