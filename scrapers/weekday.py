from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Response

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "today" in text or "just" in text:
        return today
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    return None


class WeekdayScraper(BaseScraper):
    """Weekday.works scraper — India-focused startup hiring platform.

    Login-gated SPA. Intercepts API calls for structured data.
    """

    name: str = "weekday"
    requires_login: bool = True

    async def scrape(self) -> list[Job]:
        url = "https://www.weekday.works/jobs/product-manager-jobs-in-india-remote"
        captured_api: list[dict[str, Any]] = []

        async def _intercept(response: Response) -> None:
            if response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type and (
                    "api" in response.url or "jobs" in response.url
                    or "graphql" in response.url
                ):
                    try:
                        body = await response.json()
                        captured_api.append(body)
                    except Exception:
                        pass

        page = await self._get_page(url)
        page.on("response", _intercept)

        # Check if redirected to login
        if "login" in page.url.lower() or "signin" in page.url.lower():
            self._log.warning("session.expired", redirect_url=page.url)
            await page.close()
            return []

        # Wait for job cards
        try:
            await page.wait_for_selector(
                "div[class*='job'], div[class*='card'], a[class*='job']",
                timeout=12_000,
            )
        except Exception:
            self._log.debug("wait.timeout")

        await asyncio.sleep(3)

        # Scroll to load more
        for _ in range(5):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        # Try API data first
        if captured_api:
            self._log.info("api.captured", count=len(captured_api))
            jobs = self._parse_api(captured_api)
            if jobs:
                await page.close()
                return jobs

        # Fallback: DOM parsing
        html = await page.content()
        jobs = self._parse_html(html)
        await page.close()
        return jobs

    def _parse_api(self, responses: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for resp in responses:
            items = (
                resp.get("data", {}).get("jobs", [])
                or resp.get("jobs", [])
                or resp.get("results", [])
                or []
            )
            for item in items:
                try:
                    title = item.get("title", "") or item.get("role", "")
                    company = (
                        item.get("company", {}).get("name", "")
                        if isinstance(item.get("company"), dict)
                        else item.get("companyName", "")
                    )
                    location = item.get("location", "") or item.get("city", "")
                    if isinstance(location, list):
                        location = ", ".join(location)

                    salary = item.get("salary", "") or item.get("ctc", "")
                    if isinstance(salary, dict):
                        salary = f"{salary.get('min', '')} - {salary.get('max', '')} LPA"

                    skills = item.get("skills", []) or item.get("tags", [])
                    if isinstance(skills, list) and skills and isinstance(skills[0], dict):
                        skills = [s.get("name", "") for s in skills]

                    apply_link = item.get("url", "") or item.get("link", "")
                    if apply_link and not apply_link.startswith("http"):
                        apply_link = f"https://www.weekday.works{apply_link}"

                    description = item.get("description", "") or item.get("jd", "")
                    posted_text = item.get("postedDate", "") or item.get("createdAt", "")
                    posted_date = _parse_relative_date(str(posted_text))

                    if title and company:
                        jobs.append(
                            Job(
                                platform="weekday",
                                title=title.strip(),
                                company=company.strip(),
                                location=str(location).strip(),
                                salary=str(salary).strip() if salary else None,
                                posted_date=posted_date,
                                skills=[s for s in skills if isinstance(s, str) and s],
                                description=description,
                                apply_link=apply_link or url,
                            )
                        )
                except Exception:
                    self._log.exception("api.parse_failed")
        return jobs

    def _parse_html(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        cards = (
            soup.select("div[class*='job-card']")
            or soup.select("div[class*='jobCard']")
            or soup.select("a[class*='job']")
            or soup.select("div[class*='card'][class*='listing']")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one("h2, h3, div[class*='title'], span[class*='title']")
                title = title_el.get_text(strip=True) if title_el else ""

                link_el = card.select_one("a[href]") or (card if card.name == "a" else None)
                href = link_el.get("href", "") if link_el else ""
                if href and not href.startswith("http"):
                    href = f"https://www.weekday.works{href}"

                company_el = card.select_one("span[class*='company'], div[class*='company']")
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one("span[class*='location'], div[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one("span[class*='salary'], div[class*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None

                skills_els = card.select("span[class*='skill'], span[class*='tag']")
                skills = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]

                if not (title and href):
                    continue

                jobs.append(
                    Job(
                        platform="weekday",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        skills=skills,
                        description="",
                        apply_link=href,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        return jobs
