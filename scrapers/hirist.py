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

MAX_PAGES = 3


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "today" in text or "just" in text:
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
    return None


class HiristScraper(BaseScraper):
    """Hirist.tech scraper — sister site of IIMJobs, focused on tech roles."""

    name: str = "hirist"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        params: dict[str, str] = {
            "q": "product manager",
            "loc": sp.location,
        }
        if sp.min_ctc_lpa:
            params["mn"] = str(sp.min_ctc_lpa)
        if sp.experience_min:
            params["exp"] = str(sp.experience_min)
        if page_num > 1:
            params["pg"] = str(page_num)
        return f"https://www.hirist.tech/j?{urlencode(params)}"

    async def scrape(self) -> list[Job]:
        all_jobs: list[Job] = []
        for page_num in range(1, MAX_PAGES + 1):
            url = self._build_search_url(page_num)
            self._log.info("page.scraping", page=page_num, url=url)
            try:
                jobs = await self._scrape_page(url)
            except Exception:
                self._log.exception("page.failed", page=page_num)
                break
            if not jobs:
                self._log.info("page.empty", page=page_num)
                break
            all_jobs.extend(jobs)
            self._log.info("page.collected", page=page_num, jobs=len(jobs))
            await asyncio.sleep(2)
        return all_jobs

    async def _scrape_page(self, url: str) -> list[Job]:
        page = await self._get_page(url)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Hirist uses similar layout to IIMJobs
        cards = (
            soup.select("div.job-listing")
            or soup.select("div[class*='job-list']")
            or soup.select("div.easy-card")
            or soup.select("div[class*='job-card']")
            or soup.select("tr.job")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one("a[class*='title'], h2 a, h3 a, a[href*='/j/']")
                title = title_el.get_text(strip=True) if title_el else ""
                apply_link = title_el.get("href", "") if title_el else ""
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://www.hirist.tech{apply_link}"

                company_el = card.select_one(
                    "span[class*='company'], a[class*='company'], span.employer"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one("span[class*='loc'], span[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one("span[class*='salary'], span[class*='ctc']")
                salary = salary_el.get_text(strip=True) if salary_el else None

                date_el = card.select_one("span[class*='date'], span[class*='posted']")
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                skills_els = card.select("span[class*='skill'], a[class*='skill']")
                skills = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]

                if not (title and apply_link):
                    continue

                # Fetch full description
                description = await self._fetch_description(apply_link)

                jobs.append(
                    Job(
                        platform="hirist",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=posted_date,
                        skills=skills,
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
            page = await self._get_page(url)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div[class*='job-desc'], div[class*='description'], "
                "div[class*='jd-content']"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""
            await page.close()
            return description
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
