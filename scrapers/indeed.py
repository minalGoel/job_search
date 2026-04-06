from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from urllib.parse import urlencode

import structlog
from bs4 import BeautifulSoup
from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

MAX_PAGES = 5


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "just" in text or "today" in text:
        return today
    if "yesterday" in text:
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*month", text)
    if m:
        return today - timedelta(days=int(m.group(1)) * 30)
    m = re.search(r"(\d+)\s*hour", text)
    if m:
        return today
    return None


class IndeedScraper(BaseScraper):
    name: str = "indeed"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        params: dict[str, str] = {
            "q": sp.title_keywords[0],
            "l": sp.location,
            "fromage": "7",  # last 7 days
        }
        if page_num > 1:
            params["start"] = str((page_num - 1) * 10)
        return f"https://www.indeed.co.in/jobs?{urlencode(params)}"

    async def scrape(self) -> list[Job]:
        all_jobs: list[Job] = []
        for page_num in range(1, MAX_PAGES + 1):
            url = self._build_search_url(page_num)
            self._log.info("page.scraping", page=page_num, url=url)
            try:
                jobs = await self._scrape_page(url, page_num)
            except Exception:
                self._log.exception("page.failed", page=page_num)
                break
            if not jobs:
                self._log.info("page.empty", page=page_num)
                break
            all_jobs.extend(jobs)
            self._log.info("page.collected", page=page_num, jobs=len(jobs))
            await asyncio.sleep(3)
        return all_jobs

    async def _scrape_page(self, url: str, page_num: int) -> list[Job]:
        page = await self._get_page(url)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        cards = (
            soup.select("div.job_seen_beacon")
            or soup.select("div.jobsearch-ResultsList > div")
            or soup.select("div[class*='cardOutline']")
            or soup.select("li div[class*='result']")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one(
                    "h2.jobTitle a, a[class*='jcs-JobTitle'], "
                    "h2 a span, a[data-jk]"
                )
                title = title_el.get_text(strip=True) if title_el else ""
                href = title_el.get("href", "") if title_el else ""
                apply_link = f"https://www.indeed.co.in{href}" if href and not href.startswith("http") else href

                company_el = card.select_one(
                    "span[data-testid='company-name'], span.companyName, "
                    "span[class*='company']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one(
                    "div[data-testid='text-location'], div.companyLocation, "
                    "span[class*='location']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one(
                    "div[class*='salary'], span[class*='salary'], "
                    "div[class*='metadata'][class*='salary']"
                )
                salary = salary_el.get_text(strip=True) if salary_el else None

                date_el = card.select_one(
                    "span[class*='date'], span[data-testid*='date']"
                )
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                if not (title and apply_link):
                    continue

                description = await self._fetch_description(apply_link)

                jobs.append(
                    Job(
                        platform="indeed",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=posted_date,
                        skills=[],
                        description=description,
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        await page.close()
        return jobs

    async def _fetch_description(self, url: str) -> str:
        if not url:
            return ""
        try:
            detail_page = await self._get_page(url)
            html = await detail_page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div#jobDescriptionText, div[class*='jobsearch-jobDescriptionText'], "
                "div[class*='job-desc']"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""
            await detail_page.close()
            return description
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
