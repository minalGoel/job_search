from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page, Response

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

MAX_PAGES = 5


def _parse_relative_date(text: str) -> date | None:
    """Convert relative date strings to an actual date."""
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "just now" in text or "today" in text:
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


class FounditScraper(BaseScraper):
    name: str = "foundit"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        keyword = "+".join(sp.title_keywords[0].split())
        params: dict[str, str] = {
            "query": keyword,
            "locations": sp.location,
            "sort": "1",  # sort by relevance
        }
        # NOTE: salary param omitted — it causes zero results on foundit
        # Experience range intentionally broadened to avoid filtering too aggressively
        params["experienceRanges"] = "3~15"
        if page_num > 1:
            params["start"] = str((page_num - 1) * 15)
        return f"https://www.foundit.in/srp/results?{urlencode(params)}"

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
        """Try intercepting JSON API calls, fall back to HTML parsing.

        Registers the response handler BEFORE page.goto() so the initial
        API response on first load is not missed.
        """
        captured_responses: list[dict[str, Any]] = []

        async def _intercept(response: Response) -> None:
            resp_url = response.url
            if (
                response.status == 200
                and ("api" in resp_url or "middleware" in resp_url or "search" in resp_url
                     or "srp" in resp_url or "jobs" in resp_url)
                and "application/json" in (response.headers.get("content-type", ""))
            ):
                try:
                    body = await response.json()
                    if isinstance(body, dict) and (
                        body.get("jobDetails") or body.get("searchResult") or body.get("data")
                    ):
                        captured_responses.append(body)
                except Exception:
                    pass

        # Register handler BEFORE goto so the first-load API call is captured
        context = await self.bm.get_context(self.name, Path("cookies"))
        page = await context.new_page()
        page.on("response", _intercept)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            self._log.debug("page.goto_timeout", page=page_num)

        await asyncio.sleep(4)

        # --- Strategy 1: JSON API ---
        if captured_responses:
            self._log.info("api.captured", count=len(captured_responses))
            jobs = self._parse_api_response(captured_responses)
            if jobs:
                await page.close()
                return jobs

        # --- Strategy 2: HTML fallback ---
        self._log.info("fallback.html", page=page_num)
        html = await page.content()
        jobs = await self._parse_html(html, page)
        await page.close()
        return jobs

    def _parse_api_response(self, responses: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for resp in responses:
            if not isinstance(resp, dict):
                continue
            # Foundit may nest results under different keys
            data = resp.get("data")
            if isinstance(data, dict):
                data_items = data.get("jobs", []) or data.get("jobDetails", [])
            elif isinstance(data, list):
                # Check if items look like job listings (have title/designation)
                data_items = data if data and isinstance(data[0], dict) and (
                    data[0].get("title") or data[0].get("designation")
                ) else []
            else:
                data_items = []
            sr = resp.get("searchResult", {})
            items = (
                resp.get("jobDetails", [])
                or (sr.get("jobDetails", []) if isinstance(sr, dict) else [])
                or data_items
                or []
            )
            for item in items:
                try:
                    title = item.get("title", "") or item.get("designation", "")
                    company = item.get("companyName", "") or item.get("company", "")
                    location = item.get("locations", "") or item.get("location", "")
                    if isinstance(location, list):
                        location = ", ".join(location)
                    salary = item.get("salary", "") or item.get("salaryRange", "")
                    if isinstance(salary, dict):
                        min_sal = salary.get("min", "")
                        max_sal = salary.get("max", "")
                        salary = f"{min_sal} - {max_sal}" if min_sal else ""
                    skills_raw = item.get("skills", []) or item.get("keySkills", [])
                    if isinstance(skills_raw, str):
                        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
                    elif isinstance(skills_raw, list):
                        skills = [
                            (s.get("name", "") if isinstance(s, dict) else str(s)).strip()
                            for s in skills_raw
                        ]
                    else:
                        skills = []
                    apply_link = item.get("jobURL", "") or item.get("url", "") or item.get("applyUrl", "")
                    if apply_link and not apply_link.startswith("http"):
                        apply_link = f"https://www.foundit.in{apply_link}"
                    posted_text = item.get("postedDate", "") or item.get("createdDate", "")
                    posted_date = _parse_relative_date(str(posted_text))
                    description = item.get("jobDescription", "") or item.get("description", "")

                    if title and company and apply_link:
                        jobs.append(
                            Job(
                                platform="foundit",
                                title=title.strip(),
                                company=company.strip(),
                                location=location.strip() if isinstance(location, str) else location,
                                salary=salary.strip() if salary else None,
                                posted_date=posted_date,
                                skills=[s for s in skills if s],
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

        # Confirmed live selectors (April 2026): cards have id="{jobId}"
        cards = soup.select("div.cardContainer")
        if not cards:
            cards = (
                soup.select("div.srpResultCardContainer")
                or soup.select("div[class*='jobCard']")
                or soup.select("div[data-job-id]")
            )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                # Title
                title_el = card.select_one("div.jobTitle")
                title = title_el.get_text(strip=True) if title_el else ""

                # Apply link via card id (confirmed: <div class="cardContainer" id="48540761">)
                job_id = card.get("id", "")
                apply_link = f"https://www.foundit.in/job/{job_id}" if job_id else ""

                # Company
                company_el = card.select_one("div.companyName")
                company = company_el.get_text(strip=True) if company_el else ""

                # bodyRow divs: [experience, salary (optional), location]
                body_rows = [el.get_text(strip=True) for el in card.select("div.bodyRow") if el.get_text(strip=True)]
                location = body_rows[-1] if body_rows else ""
                salary = body_rows[1] if len(body_rows) >= 3 else None

                # Date
                date_el = card.select_one("div.timeText")
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                skills: list[str] = []

                if not (title and apply_link):
                    continue

                jobs.append(
                    Job(
                        platform="foundit",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=posted_date,
                        skills=skills,
                        description="",
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        return jobs

    async def _fetch_description(self, url: str) -> str:
        """Navigate to a job detail page and extract the full JD."""
        if not url:
            return ""
        try:
            page = await self._get_page(url)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div[class*='job-desc'], div[class*='jd-desc'], "
                "div[class*='description'], section[class*='job-detail'], "
                "div[class*='jobDescription']"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""
            await page.close()
            return description
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
