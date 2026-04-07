from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location

log = structlog.get_logger(__name__)

class CutshortScraper(BaseScraper):
    name: str = "cutshort"
    requires_login: bool = True

    async def scrape(self) -> list[Job]:
        keyword_slug = self.search_params.title_keywords[0].replace(" ", "-")
        url = f"https://cutshort.io/jobs/{keyword_slug}-jobs-in-delhi-ncr-gurgaon-noida"
        self._log.info("page.scraping", url=url)

        page = None
        try:
            page = await self._get_page(url)

            # Check if redirected to login
            if "login" in page.url.lower() or "signin" in page.url.lower():
                self._log.warning("session.expired", redirect_url=page.url)
                return []

            # Wait for Next.js hydration
            try:
                await page.wait_for_selector("#__NEXT_DATA__", timeout=12_000)
            except Exception:
                self._log.debug("wait.next_data.timeout")

            await asyncio.sleep(2)

            jobs = await self._parse_next_data(page)

            if not jobs:
                # Fallback: HTML parsing
                html = await page.content()
                jobs = self._parse_html(html)

            return jobs
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _parse_next_data(self, page: Any) -> list[Job]:
        """Extract jobs from Next.js __NEXT_DATA__ JSON."""
        try:
            next_data_text = await page.eval_on_selector(
                "#__NEXT_DATA__", "el => el.textContent"
            )
            data = json.loads(next_data_text)
            dehydrated = (
                data.get("props", {})
                .get("pageProps", {})
                .get("dehydratedState", {})
            )
            queries = dehydrated.get("queries", []) if isinstance(dehydrated, dict) else []

            raw_jobs: list[dict[str, Any]] = []
            for q in queries:
                qk = str(q.get("queryKey", ""))
                if "jobListData" in qk:
                    page_data = (
                        q.get("state", {})
                        .get("data", {})
                        .get("data", {})
                        .get("pageData", {})
                    )
                    raw_jobs = page_data.get("jobs", [])
                    break

            self._log.info("next_data.jobs_found", count=len(raw_jobs))
            return self._parse_jobs(raw_jobs)
        except Exception:
            self._log.debug("next_data.parse_failed")
            return []

    def _parse_jobs(self, raw_jobs: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for item in raw_jobs:
            try:
                title = item.get("headline", "").strip()

                company_data = item.get("companyDetails") or {}
                company = company_data.get("name", "").strip() if isinstance(company_data, dict) else ""

                location = item.get("locationsText", "")
                if not location and isinstance(item.get("locations"), list):
                    location = ", ".join(item["locations"])

                # Salary: prefer text (e.g. "₹15L - ₹40L / yr"), else build from range
                salary = item.get("salaryRangeText", "")
                if not salary:
                    sal_range = item.get("salaryRange") or {}
                    if isinstance(sal_range, dict):
                        min_s = sal_range.get("userMinVanity") or sal_range.get("min")
                        max_s = sal_range.get("userMaxVanity") or sal_range.get("max")
                        if min_s and max_s and (min_s > 0 or max_s > 0):
                            salary = f"₹{min_s // 100000}L - ₹{max_s // 100000}L"

                skills = item.get("allSkills", []) or []
                if isinstance(skills, list):
                    skills = [s.strip() for s in skills if isinstance(s, str) and s.strip()]

                apply_link = item.get("publicUrl", "") or item.get("authApplyUrl", "")
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://cutshort.io{apply_link}"

                if title and company and apply_link:
                    loc = str(location).strip()
                    if not is_acceptable_location(loc):
                        self._log.debug("cutshort.location_rejected", title=title, location=loc)
                        continue
                    jobs.append(
                        Job(
                            platform="cutshort",
                            title=title,
                            company=company,
                            location=loc,
                            salary=salary.strip() if salary else None,
                            posted_date=None,
                            skills=skills,
                            description="",
                            apply_link=apply_link,
                        )
                    )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs

    def _parse_html(self, html: str) -> list[Job]:
        """Fallback HTML parser."""
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
                apply_link = (
                    f"https://cutshort.io{href}"
                    if href and not href.startswith("http")
                    else href
                )

                company_el = card.select_one(
                    "span[class*='company'], div[class*='company'], p[class*='company']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                location_el = card.select_one(
                    "span[class*='location'], div[class*='location'], p[class*='location']"
                )
                location = location_el.get_text(strip=True) if location_el else None

                if not (title and apply_link):
                    continue

                if not is_acceptable_location(location):
                    self._log.debug("card.location_rejected", title=title, location=location)
                    continue

                jobs.append(
                    Job(
                        platform="cutshort",
                        title=title,
                        company=company,
                        location=location or "",
                        salary=None,
                        posted_date=None,
                        skills=[],
                        description="",
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        return jobs
