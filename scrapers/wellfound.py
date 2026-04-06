from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

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
    return None


class WellfoundScraper(BaseScraper):
    name: str = "wellfound"
    requires_login: bool = True  # blank page in headless; requires logged-in session

    def _build_search_url(self, page_num: int = 1) -> str:
        base = "https://wellfound.com/jobs"
        params = f"?role=product-manager&location=delhi"
        if page_num > 1:
            params += f"&page={page_num}"
        return f"{base}{params}"

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
            await asyncio.sleep(3)
        return all_jobs

    async def _scrape_page(self, url: str) -> list[Job]:
        page = await self._get_page(url)

        # Wait for React to render job cards
        try:
            await page.wait_for_selector(
                "div[class*='job'], div[class*='styles_result'], "
                "a[class*='job-listing']",
                timeout=12_000,
            )
        except Exception:
            self._log.debug("wait.timeout")

        await asyncio.sleep(2)
        html = await page.content()

        # Detect Cloudflare bot challenge (wellfound uses captcha-delivery.com)
        if "captcha-delivery.com" in html or "challenge-platform" in html:
            self._log.warning("cloudflare.challenge_detected", url=url)
            await page.close()
            return []

        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        cards = (
            soup.select("div[class*='styles_result']")
            or soup.select("div[class*='job-listing']")
            or soup.select("div[class*='StartupResult']")
            or soup.select("div[class*='browse-table-row']")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one(
                    "h2, h3, a[class*='title'], div[class*='title'], "
                    "span[class*='title']"
                )
                title = title_el.get_text(strip=True) if title_el else ""

                link_el = card.select_one("a[href*='/jobs/'], a[href*='/company/']")
                href = link_el.get("href", "") if link_el else ""
                apply_link = (
                    f"https://wellfound.com{href}"
                    if href and not href.startswith("http")
                    else href
                )

                company_el = card.select_one(
                    "h2, a[class*='company'], span[class*='company'], "
                    "div[class*='company']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one(
                    "span[class*='location'], div[class*='location']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one(
                    "span[class*='salary'], div[class*='compensation']"
                )
                salary = salary_el.get_text(strip=True) if salary_el else None

                skills_els = card.select(
                    "span[class*='skill'], span[class*='tag'], a[class*='tag']"
                )
                skills = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]

                if not (title and apply_link):
                    continue

                # Fetch full description
                description = await self._fetch_description(apply_link)

                jobs.append(
                    Job(
                        platform="wellfound",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
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
            await page.wait_for_selector(
                "div[class*='description'], div[class*='content']",
                timeout=8_000,
            )
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div[class*='description'], div[class*='job-description'], "
                "div[class*='content'] p"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""
            await page.close()
            return description
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
