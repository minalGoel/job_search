from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

MAX_PAGES = 3


def _parse_relative_date(text: str) -> date | None:
    """Convert strings like '2 days ago', 'Today', 'Posted 1 week ago'."""
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
    m = re.search(r"(\d+)\s*hour", text)
    if m:
        return today
    # Try absolute date like "03 Apr 2026"
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class IIMJobsScraper(BaseScraper):
    name: str = "iimjobs"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        keyword = "+".join(sp.title_keywords[0].split())
        params: dict[str, str] = {
            "q": keyword,
            "loc": sp.location,
        }
        if sp.min_ctc_lpa:
            params["mn"] = str(sp.min_ctc_lpa)
        if page_num > 1:
            params["pg"] = str(page_num)
        return f"https://www.iimjobs.com/j?{urlencode(params)}"

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

        # IIMJobs uses server-rendered listing cards
        cards = soup.select("div.job-listing") or soup.select(
            "div[class*='job-list']"
        ) or soup.select("div.easy-card")

        # Fallback: try table rows or generic list items
        if not cards:
            cards = soup.select("tr.job") or soup.select("li[class*='job']")

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                # Title and link
                title_el = card.select_one("a[class*='title'], a[class*='job-title'], h3 a, h2 a")
                if not title_el:
                    title_el = card.select_one("a[href*='/j/']")
                title = title_el.get_text(strip=True) if title_el else ""
                apply_link = title_el.get("href", "") if title_el else ""
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://www.iimjobs.com{apply_link}"

                # Company
                company_el = card.select_one(
                    "span[class*='company'], div[class*='company'], "
                    "a[class*='company'], span.employer"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                # Location
                loc_el = card.select_one(
                    "span[class*='loc'], div[class*='location'], "
                    "span[class*='location']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                # Salary
                salary_el = card.select_one(
                    "span[class*='salary'], span[class*='ctc'], "
                    "div[class*='salary']"
                )
                salary = salary_el.get_text(strip=True) if salary_el else None

                # Posted date
                date_el = card.select_one(
                    "span[class*='date'], span[class*='posted'], "
                    "div[class*='date'], time"
                )
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                if not (title and apply_link):
                    continue

                # Fetch full JD and skills from individual page
                description, skills = await self._fetch_job_details(apply_link)

                jobs.append(
                    Job(
                        platform="iimjobs",
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

    async def _fetch_job_details(self, url: str) -> tuple[str, list[str]]:
        """Navigate to a job detail page and return (description, skills)."""
        if not url:
            return "", []
        try:
            page = await self._get_page(url)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Description
            jd_el = soup.select_one(
                "div[class*='job-desc'], div[class*='jd-content'], "
                "div[class*='description'], div.job-detail-description"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""

            # Skills / key skills section
            skills: list[str] = []
            skills_section = soup.select_one(
                "div[class*='skill'], div[class*='key-skill'], "
                "span[class*='skill-list']"
            )
            if skills_section:
                skill_tags = skills_section.select("a, span, li")
                skills = [
                    s.get_text(strip=True)
                    for s in skill_tags
                    if s.get_text(strip=True)
                ]
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_skills: list[str] = []
            for s in skills:
                lower = s.lower()
                if lower not in seen:
                    seen.add(lower)
                    unique_skills.append(s)

            await page.close()
            return description, unique_skills
        except Exception:
            self._log.debug("detail.fetch_failed", url=url)
            return "", []
