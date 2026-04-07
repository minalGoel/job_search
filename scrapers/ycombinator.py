from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location, explain as explain_location

log = structlog.get_logger(__name__)


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "today" in text or "just" in text or "hour" in text:
        return today
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*month", text)
    if m:
        return today - timedelta(days=int(m.group(1)) * 30)
    return None


class YCombinatorScraper(BaseScraper):
    """Scrape YC Work at a Startup for PM roles.

    YC consolidated all job listings to ycombinator.com/jobs with role-based
    tabs.  Product Manager jobs live at /jobs/role/product-manager.

    Job link pattern: /companies/{company-slug}/jobs/{job-id}-{title-slug}
    """

    name: str = "ycombinator"
    requires_login: bool = False

    async def scrape(self) -> list[Job]:
        url = "https://www.ycombinator.com/jobs/role/product-manager"
        self._log.info("page.scraping", url=url)

        page = None
        try:
            page = await self._get_page(url)

            # Wait for job cards to render (they're SSR'd but may lazy-load)
            try:
                await page.wait_for_selector(
                    'a[href*="/companies/"][href*="/jobs/"]',
                    timeout=15_000,
                )
            except Exception:
                self._log.debug("wait.timeout")

            await asyncio.sleep(2)

            html = await page.content()
            jobs = self._parse_page(html)
            self._log.info("page.collected", url=url, jobs=len(jobs))
            return jobs
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    def _parse_page(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Job title links follow: /companies/{slug}/jobs/{id}-{title-slug}
        job_links = soup.select('a[href*="/companies/"][href*="/jobs/"]')
        self._log.info("html.job_links_found", count=len(job_links))

        pm_keywords = {
            "product manager", "product management", "senior pm",
            "head of product", "director of product", "director product",
            "vp product", "chief product", "associate pm",
        }

        seen: set[str] = set()

        for link in job_links:
            try:
                href = link.get("href", "")
                title = link.get_text(strip=True)

                if not title or href in seen:
                    continue
                seen.add(href)

                # Filter to PM roles only
                if not any(kw in title.lower() for kw in pm_keywords):
                    continue

                apply_link = (
                    f"https://www.ycombinator.com{href}"
                    if href.startswith("/")
                    else href
                )

                # Walk up to find the card container
                # Structure: card > [company info, job info row]
                # Company name is in a sibling/parent span or div
                card = link.parent
                for _ in range(4):
                    if card and len(card.select('a[href*="/jobs/"]')) >= 1:
                        break
                    card = card.parent if card else None

                company = ""
                location = ""
                salary = None
                posted_date = None

                if card:
                    card_text = card.get_text(" ", strip=True)

                    # Extract company name — look for links to /companies/
                    company_links = card.select('a[href*="/companies/"]')
                    for cl in company_links:
                        company_text = cl.get_text(strip=True)
                        # Company links have the company name (not the job title)
                        if company_text and company_text != title:
                            company = company_text
                            break

                    # Location and salary: look for patterns like "•location•"
                    # Text typically: "Full-time•Engineering•$100K - $200K•Remote"
                    # or "Full-time•Engineering•₹XM INR•IN / Remote"
                    parts = [p.strip() for p in card_text.split("•")]
                    location_markers = (
                        "Remote", "India", "Delhi", "Gurugram", "Gurgaon", "Noida",
                        "Mumbai", "Bangalore", "Bengaluru", "Hyderabad", "Chennai", "Pune",
                        "CA,", "NY,", "WA,", "TX,", "MA,", "US", "UK", "EU",
                        "London", "Berlin", "Paris", "Tel Aviv", "Toronto", "Singapore",
                        "San Francisco", "New York",
                    )
                    for part in parts:
                        if not location and any(loc in part for loc in location_markers):
                            location = part  # capture FIRST match, not last
                        if not salary and any(curr in part for curr in ["$", "£", "€", "₹", "CAD", "AUD", "LPA"]):
                            salary = part

                    # Date: look for "N days ago" / "N hours ago"
                    date_m = re.search(r"(\d+\s*(?:day|hour|week|month)s?\s*ago|about .+? ago)", card_text, re.I)
                    if date_m:
                        posted_date = _parse_relative_date(date_m.group(1))

                if title and apply_link:
                    # Reject jobs outside Delhi NCR / global remote
                    if not is_acceptable_location(location):
                        self._log.debug("yc.filtered_location",
                                        title=title, company=company,
                                        reason=explain_location(location))
                        continue
                    jobs.append(
                        Job(
                            platform="ycombinator",
                            title=title,
                            company=company,
                            location=location,
                            salary=salary,
                            skills=[],
                            posted_date=posted_date,
                            description="YC-backed startup",
                            apply_link=apply_link,
                        )
                    )
            except Exception:
                self._log.exception("card.parse_failed")

        return jobs
