"""
yc_startups/founder_scraper.py — Scrape founder data from YC company pages.

Each company page at ycombinator.com/companies/{slug} contains:
  - Founder names (from img alt text)
  - Founder titles (Founder/CEO, CTO, etc.)
  - LinkedIn profile URLs
  - Twitter/X profile URLs

This module fetches pages via httpx (server-rendered, no browser needed)
and parses with BeautifulSoup. Uses async concurrency with a semaphore
to avoid hammering YC servers.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

YC_COMPANY_URL = "https://www.ycombinator.com/companies/{slug}"

# Titles that indicate a founder/exec role
_TITLE_KEYWORDS = frozenset([
    "founder", "ceo", "cto", "coo", "cfo", "president", "chief",
    "co-founder", "cofounder", "managing director",
])

# Image alt texts to skip (not people)
_SKIP_ALTS = frozenset([
    "twitter account", "x (twitter) logo", "linkedin profile",
    "y combinator", "github profile", "facebook", "crunchbase",
])


def _is_person_name(alt: str, company_name: str) -> bool:
    """Check if an img alt text is likely a person's name."""
    if not alt or len(alt) < 3 or len(alt) > 60:
        return False
    lower = alt.lower().strip()
    if lower in _SKIP_ALTS:
        return False
    if lower == company_name.lower().strip():
        return False
    if any(kw in lower for kw in ["logo", "account", "profile", "icon", "avatar"]):
        return False
    # Person names typically have 2+ words (but allow single names)
    return True


def _extract_founders_from_html(html: str, company_name: str) -> list[dict]:
    """Extract founder data from a YC company page HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.error("yc.founders.bs4_not_installed")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Find the "Founders" or "Active Founders" section header
    founders_div = soup.find("div", string=re.compile(r"^(?:Active )?Founders$"))
    if not founders_div:
        return []

    # The founder cards are in the next sibling div
    container = founders_div.find_next_sibling("div")
    if not container:
        # Fallback: try parent container
        container = founders_div.parent
    if not container:
        return []

    founders: list[dict] = []
    seen_names: set[str] = set()

    imgs = container.find_all("img", alt=True)

    for img in imgs:
        alt = (img.get("alt") or "").strip()
        if not _is_person_name(alt, company_name):
            continue
        if alt in seen_names:
            continue
        seen_names.add(alt)

        # Walk up to find the founder card that contains social links
        card = img.parent
        for _ in range(5):  # max 5 levels up
            if card is None or card == container:
                break
            links_in_card = card.find_all("a", href=True)
            has_social = any(
                "linkedin.com" in a["href"] or "twitter.com" in a["href"] or "x.com" in a["href"]
                for a in links_in_card
            )
            if has_social:
                break
            card = card.parent

        if not card or card == container:
            card = img.parent.parent  # fallback

        # Extract LinkedIn
        linkedin = ""
        twitter = ""
        for a in card.find_all("a", href=True):
            href = a["href"]
            if ("linkedin.com/in/" in href or "linkedin.com/pub/" in href) and not linkedin:
                linkedin = href
            elif ("twitter.com/" in href or "x.com/" in href) and not twitter:
                # Skip company twitter handle
                handle = href.rstrip("/").rsplit("/", 1)[-1].lower()
                if handle != company_name.lower().replace(" ", ""):
                    twitter = href

        # Extract title
        title = ""
        for el in card.find_all(string=True):
            t = el.strip()
            if t and 3 < len(t) < 50 and any(kw in t.lower() for kw in _TITLE_KEYWORDS):
                title = t
                break

        founders.append({
            "name": alt,
            "title": title,
            "linkedin": linkedin,
            "twitter": twitter,
        })

    return founders


async def scrape_founders_for_companies(
    companies: list[dict],
    max_concurrent: int = 10,
    delay_between: float = 0.3,
) -> dict[str, list[dict]]:
    """Scrape founder data for a batch of YC companies.

    Args:
        companies: Company dicts with at least 'id' and 'company_slug'.
        max_concurrent: Max concurrent HTTP requests.
        delay_between: Seconds between each request to be polite.

    Returns:
        Dict mapping company_id -> list of founder dicts.
    """
    results: dict[str, list[dict]] = {}
    semaphore = asyncio.Semaphore(max_concurrent)
    total = len(companies)

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=max_concurrent),
        headers={"User-Agent": "Mozilla/5.0 (compatible; JobSearchBot/1.0)"},
    ) as client:
        async def fetch_one(company: dict, idx: int) -> None:
            cid = company["id"]
            slug = company.get("company_slug", "")
            name = company.get("company_name", "")
            if not slug:
                return

            async with semaphore:
                try:
                    url = YC_COMPANY_URL.format(slug=slug)
                    resp = await client.get(url)
                    if resp.status_code == 404:
                        log.debug("yc.founders.404", slug=slug)
                        return
                    resp.raise_for_status()

                    founders = _extract_founders_from_html(resp.text, name)
                    if founders:
                        results[cid] = founders

                    if (idx + 1) % 50 == 0:
                        log.info("yc.founders.progress", done=idx + 1, total=total, found=len(results))

                    await asyncio.sleep(delay_between)

                except Exception:
                    log.debug("yc.founders.fetch_error", slug=slug)

        tasks = [fetch_one(c, i) for i, c in enumerate(companies)]
        await asyncio.gather(*tasks)

    log.info("yc.founders.done", total_companies=total, with_founders=len(results))
    return results


async def scrape_and_store_founders(
    db: object,
    companies: list[dict] | None = None,
    max_concurrent: int = 10,
    limit: int = 0,
) -> int:
    """Scrape founders from YC website and store in DB.

    Args:
        db: JobDB instance.
        companies: Optional list of company dicts. If None, reads from DB.
        max_concurrent: Concurrent requests.
        limit: Max companies to process. 0 = all.

    Returns:
        Number of founder contacts stored.
    """
    if companies is None:
        companies = db.get_yc_companies()  # type: ignore[union-attr]

    if limit > 0:
        companies = companies[:limit]

    if not companies:
        log.info("yc.founders.no_companies")
        return 0

    # Scrape
    founder_map = await scrape_founders_for_companies(
        companies, max_concurrent=max_concurrent,
    )

    # Store founders in DB and update company records
    now = datetime.now().isoformat()
    stored = 0

    for company in companies:
        cid = company["id"]
        founders = founder_map.get(cid, [])

        # Update the company's founders JSON field
        if founders:
            db.upsert_yc_company({  # type: ignore[union-attr]
                **company,
                "founders": founders,
                "is_hiring": int(company.get("is_hiring", False)),
                "is_hiring_pm": int(company.get("is_hiring_pm", False)),
            })

            # Also store as individual founder contacts
            for f in founders:
                from yc_startups.models import YCFounderContact
                fc = YCFounderContact(
                    yc_company_id=cid,
                    founder_name=f["name"],
                    founder_title=f.get("title", ""),
                    founder_linkedin=f.get("linkedin", ""),
                    founder_twitter=f.get("twitter", ""),
                    enrichment_source="yc_website",
                    enriched_at=now,
                )
                db.upsert_yc_founder_contact({  # type: ignore[union-attr]
                    "id": fc.id,
                    "yc_company_id": cid,
                    "founder_name": f["name"],
                    "founder_title": f.get("title", ""),
                    "founder_email": "",  # No email from YC page
                    "founder_email_verified": 0,
                    "founder_linkedin": f.get("linkedin", ""),
                    "founder_twitter": f.get("twitter", ""),
                    "enrichment_source": "yc_website",
                    "enriched_at": now,
                })
                stored += 1

    db.conn.commit()  # type: ignore[union-attr]
    log.info("yc.founders.stored", contacts=stored, companies_with_founders=len(founder_map))
    return stored
