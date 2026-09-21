from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus, urlencode

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page, Response

from models.job import Job
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location

log = structlog.get_logger(__name__)

MAX_PAGES = 5


def _parse_relative_date(text: str) -> date | None:
    """Convert strings like '2 days ago', 'Just now', '1 month ago' to a date."""
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "just now" in text or "today" in text:
        return today
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*month", text)
    if m:
        return today - timedelta(days=int(m.group(1)) * 30)
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*hour", text)
    if m:
        return today
    return None


class NaukriScraper(BaseScraper):
    name: str = "naukri"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        keyword = "-".join(sp.title_keywords[0].lower().split())
        location = "delhi-ncr"
        base = f"https://www.naukri.com/{keyword}-jobs-in-{location}"
        params: dict[str, str] = {}
        if sp.experience_min:
            params["experience"] = str(sp.experience_min)
        if sp.min_ctc_lpa:
            params["salary"] = str(sp.min_ctc_lpa)
        if page_num > 1:
            params["pageNo"] = str(page_num)
        qs = urlencode(params)
        return f"{base}?{qs}" if qs else base

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
            await asyncio.sleep(2)
        return all_jobs

    async def _scrape_page(self, url: str, page_num: int) -> list[Job]:
        """Try the XHR JSON API first, fall back to HTML parsing."""
        import random
        from pathlib import Path
        captured_responses: list[dict[str, Any]] = []

        async def _intercept(response: Response) -> None:
            resp_url = response.url
            if response.status == 200 and (
                "jobapi" in resp_url or "naukri.com/jobapi" in resp_url
                or ("naukri.com" in resp_url and "search" in resp_url)
            ):
                try:
                    body = await response.json()
                    if isinstance(body, dict) and body.get("jobDetails"):
                        captured_responses.append(body)
                except Exception:
                    pass

        # Register listener BEFORE navigation so we catch the first load
        context = await self.bm.get_context(self.name, self.cookies_dir)
        page = None  # sentinel — ensures finally block is safe even if new_page() raises
        try:
            page = await context.new_page()
            page.on("response", _intercept)
            await asyncio.sleep(random.uniform(2.0, 4.0))
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            except Exception:
                # goto failed — page is likely blank; log as warning (not debug) so
                # failures are visible in run logs, then return empty rather than
                # continuing on a broken page.
                self._log.warning("page.goto_timeout", page=page_num, url=url)
                return []
            await asyncio.sleep(4)

            # --- Strategy 1: Parse captured JSON API responses ---
            if captured_responses:
                self._log.info("api.captured", count=len(captured_responses))
                jobs = self._parse_api_response(captured_responses)
                if jobs:
                    return jobs

            # --- Strategy 2: Fall back to HTML ---
            self._log.info("fallback.html", page=page_num)
            html = await page.content()
            jobs = await self._parse_html(html, page)
            return jobs

        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    def _parse_api_response(
        self, responses: list[dict[str, Any]]
    ) -> list[Job]:
        jobs: list[Job] = []
        for resp in responses:
            job_details = resp.get("jobDetails", [])
            if not job_details:
                continue
            for item in job_details:
                try:
                    title = item.get("title", "")
                    company = item.get("companyName", "")

                    # Naukri's `placeholders` is a list of {type, label} dicts
                    # where type can be "experience", "salary", "location". Earlier
                    # code indexed [0] for location which is actually experience.
                    placeholders = item.get("placeholders", []) or []
                    by_type: dict[str, str] = {}
                    for ph in placeholders:
                        if not isinstance(ph, dict):
                            continue
                        ptype = (ph.get("type") or "").lower()
                        plabel = (ph.get("label") or "").strip()
                        if ptype and plabel:
                            by_type[ptype] = plabel

                    location = by_type.get("location", "")
                    salary = by_type.get("salary") or None
                    # experience intentionally discarded; by_type.get("experience")
                    raw_skills = item.get("tagsAndSkills")
                    if isinstance(raw_skills, str):
                        skills_list = [part.strip() for part in raw_skills.split(",") if part.strip()]
                    elif isinstance(raw_skills, list):
                        skills_list = [
                            (skill.get("label", "") if isinstance(skill, dict) else str(skill)).strip()
                            for skill in raw_skills
                            if (skill.get("label", "") if isinstance(skill, dict) else str(skill)).strip()
                        ]
                    else:
                        skills_list = []
                    apply_link = item.get("jdURL", "")
                    if apply_link and not apply_link.startswith("http"):
                        apply_link = f"https://www.naukri.com{apply_link}"
                    posted_text = item.get("footerPlaceholderLabel", "")
                    posted_date = _parse_relative_date(posted_text)
                    description = item.get("jobDescription", "")

                    if title and company and apply_link:
                        loc = location.strip()
                        if not is_acceptable_location(loc):
                            self._log.debug("api.location_rejected", title=title, location=loc)
                            continue
                        jobs.append(
                            Job(
                                platform="naukri",
                                title=title.strip(),
                                company=company.strip(),
                                location=loc,
                                salary=salary.strip() if salary else None,
                                posted_date=posted_date,
                                skills=[s.strip() for s in skills_list if s.strip()],
                                description=description,
                                apply_link=apply_link,
                            )
                        )
                except Exception:
                    self._log.exception("api.parse_item_failed")
        return jobs

    async def _parse_html(self, html: str, page: Page) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Naukri uses article tags or divs with class containing 'jobTuple'
        # Confirmed live selectors (April 2026)
        cards = (
            soup.select("div.cust-job-tuple")
            or soup.select("div.srp-jobtuple-wrapper")
            or soup.select("div[class*='job-tuple']")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one("a.title")
                title = title_el.get_text(strip=True) if title_el else ""
                apply_link = title_el.get("href", "") if title_el else ""
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://www.naukri.com{apply_link}"

                company_el = card.select_one("a.comp-name, span.comp-dtls-wrap a")
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one("span.locWdth, span.loc-wrap")
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one("span.sal-wrap, span[class*='sal']")
                salary = salary_el.get_text(strip=True) if salary_el else None

                skills_el = card.select("span.dot-gt.tag-li, li.tag-li")
                skills = [s.get_text(strip=True) for s in skills_el if s.get_text(strip=True)]

                date_el = card.select_one("span.job-post-day")
                posted_date = _parse_relative_date(date_el.get_text(strip=True)) if date_el else None

                if not (title and company and apply_link):
                    continue

                if not is_acceptable_location(location):
                    self._log.debug("html.location_rejected", title=title, location=location)
                    continue

                # Fetch full description from individual job page
                description = await self._fetch_description(apply_link)

                jobs.append(
                    Job(
                        platform="naukri",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary if salary and salary != "Not disclosed" else None,
                        posted_date=posted_date,
                        skills=skills,
                        description=description,
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("html.card_parse_failed")
        return jobs

    async def _fetch_description(self, url: str) -> str:
        """Navigate to a job detail page and extract the description."""
        if not url:
            return ""
        detail_page = None
        try:
            detail_page = await self._get_page(url)
            html = await detail_page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div[class*='job-desc'], div[class*='jd-desc'], "
                "section[class*='job-desc'], div.dang-inner-html"
            )
            return jd_el.get_text(separator="\n", strip=True) if jd_el else ""
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
        finally:
            if detail_page is not None:
                try:
                    await detail_page.close()
                except Exception:
                    pass
