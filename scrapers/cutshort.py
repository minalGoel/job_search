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

MAX_LOADS = 5


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


class CutshortScraper(BaseScraper):
    name: str = "cutshort"
    requires_login: bool = True

    def _build_search_url(self) -> str:
        sp = self.search_params
        keyword = "+".join(sp.title_keywords[0].split())
        return f"https://cutshort.io/jobs?q={keyword}&city=Delhi+NCR"

    async def scrape(self) -> list[Job]:
        url = self._build_search_url()
        captured_api: list[dict[str, Any]] = []

        async def _intercept(response: Response) -> None:
            if response.status == 200 and (
                "graphql" in response.url
                or "api" in response.url
                or "jobs" in response.url
            ):
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        body = await response.json()
                        captured_api.append(body)
                    except Exception:
                        pass

        page = await self._get_page(url)
        page.on("response", _intercept)

        # Wait for React content to render
        try:
            await page.wait_for_selector(
                "div[class*='job'], div[class*='card'], a[class*='job']",
                timeout=10_000,
            )
        except Exception:
            self._log.debug("wait.timeout")

        await asyncio.sleep(3)

        # Scroll to load more results
        for load in range(MAX_LOADS):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            # Check for a "Load More" button
            load_more = await page.query_selector(
                "button:has-text('Load More'), button:has-text('Show more'), "
                "a:has-text('Load More')"
            )
            if load_more:
                await load_more.click()
                await asyncio.sleep(2)

        # Try API data first
        if captured_api:
            self._log.info("api.captured", count=len(captured_api))
            jobs = self._parse_api(captured_api)
            if jobs:
                await page.close()
                return jobs

        # Fallback: parse rendered DOM
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
                    title = item.get("title", "") or item.get("name", "")
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
                    skills = item.get("skills", []) or item.get("technologies", [])
                    if isinstance(skills, list) and skills and isinstance(skills[0], dict):
                        skills = [s.get("name", "") for s in skills]
                    apply_link = item.get("url", "") or item.get("link", "")
                    if apply_link and not apply_link.startswith("http"):
                        apply_link = f"https://cutshort.io{apply_link}"
                    description = item.get("description", "") or item.get("jobDescription", "")
                    posted_text = item.get("postedDate", "") or item.get("createdAt", "")
                    posted_date = _parse_relative_date(str(posted_text))

                    if title and company and apply_link:
                        jobs.append(
                            Job(
                                platform="cutshort",
                                title=title.strip(),
                                company=company.strip(),
                                location=str(location).strip(),
                                salary=str(salary).strip() if salary else None,
                                posted_date=posted_date,
                                skills=[s for s in skills if isinstance(s, str) and s],
                                description=description,
                                apply_link=apply_link,
                            )
                        )
                except Exception:
                    self._log.exception("api.parse_item_failed")
        return jobs

    def _parse_html(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        cards = (
            soup.select("div[class*='job-card']")
            or soup.select("div[class*='jobCard']")
            or soup.select("a[class*='job-card']")
            or soup.select("div[class*='listing']")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one("h2, h3, a[class*='title'], div[class*='title']")
                title = title_el.get_text(strip=True) if title_el else ""

                link_el = card.select_one("a[href]") or title_el
                href = link_el.get("href", "") if link_el else ""
                apply_link = f"https://cutshort.io{href}" if href and not href.startswith("http") else href

                company_el = card.select_one(
                    "span[class*='company'], div[class*='company'], p[class*='company']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one("span[class*='loc'], div[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one("span[class*='salary'], div[class*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None

                skills_els = card.select("span[class*='skill'], span[class*='tag']")
                skills = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]

                date_el = card.select_one("span[class*='date'], time")
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                if not (title and apply_link):
                    continue

                jobs.append(
                    Job(
                        platform="cutshort",
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
