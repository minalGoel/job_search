from __future__ import annotations

import asyncio
import random
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "just" in text or "today" in text:
        return today
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*h", text)
    if m:
        return today
    return None


class GlassdoorScraper(BaseScraper):
    """Glassdoor scraper — BEST EFFORT only.

    Cloudflare protection makes this the least reliable scraper.
    Returns empty list gracefully on any blocking.
    """

    name: str = "glassdoor"
    requires_login: bool = False

    def _build_search_url(self) -> str:
        return (
            "https://www.glassdoor.co.in/Job/"
            "delhi-ncr-product-manager-jobs-"
            "SRCH_IL.0,9_IC2891385_KO10,25.htm"
        )

    async def scrape(self) -> list[Job]:
        url = self._build_search_url()
        self._log.info("glassdoor.attempt", url=url)

        # Extra delay before even trying
        await asyncio.sleep(random.uniform(5.0, 10.0))

        try:
            page = await self._get_page(url)
        except Exception:
            self._log.warning("glassdoor.blocked_on_load")
            return []

        # Check for Cloudflare challenge
        content = await page.content()
        if "challenge" in content.lower() or "captcha" in content.lower():
            self._log.warning("glassdoor.cloudflare_challenge")
            await page.close()
            return []

        await asyncio.sleep(3)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        cards = (
            soup.select("li.react-job-listing")
            or soup.select("li[data-test='jobListing']")
            or soup.select("li[class*='JobsList_jobListItem']")
            or soup.select("ul[class*='JobsList'] > li")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one(
                    "a[data-test='job-link'], a[class*='jobTitle'], "
                    "div[class*='job-title'] a"
                )
                title = title_el.get_text(strip=True) if title_el else ""
                href = title_el.get("href", "") if title_el else ""
                apply_link = (
                    f"https://www.glassdoor.co.in{href}"
                    if href and not href.startswith("http")
                    else href
                )

                company_el = card.select_one(
                    "span[class*='EmployerProfile'], "
                    "div[class*='employer'] span, "
                    "a[data-test='employer-short-name']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one(
                    "span[class*='location'], div[class*='location']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one(
                    "span[class*='salary'], div[class*='salary']"
                )
                salary = salary_el.get_text(strip=True) if salary_el else None

                date_el = card.select_one(
                    "div[data-test='job-age'], span[class*='ago']"
                )
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                if not (title and apply_link):
                    continue

                # No detail page fetching for Glassdoor (too risky)
                jobs.append(
                    Job(
                        platform="glassdoor",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=posted_date,
                        skills=[],
                        description="",
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        await page.close()
        self._log.info("glassdoor.done", jobs_found=len(jobs))
        return jobs
