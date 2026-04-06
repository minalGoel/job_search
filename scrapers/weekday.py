from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Response

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    # ISO datetime string e.g. "2026-04-01T11:08:44.000Z"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
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
    """Weekday.works scraper.

    Weekday uses Next.js SSR — job data is embedded in the ``__NEXT_DATA__``
    script tag as ``props.pageProps.jobs``.  We extract that JSON directly
    instead of relying on API interception or class-based DOM selectors.
    """

    name: str = "weekday"
    requires_login: bool = True

    async def scrape(self) -> list[Job]:
        url = "https://www.weekday.works/jobs/in/product-manager/ncr"
        self._log.info("page.scraping", url=url)

        page = await self._get_page(url)

        # Check if redirected to login
        if "login" in page.url.lower() or "signin" in page.url.lower():
            self._log.warning("session.expired", redirect_url=page.url)
            await page.close()
            return []

        # Wait for Next.js hydration to complete
        try:
            await page.wait_for_selector("#__NEXT_DATA__", timeout=12_000)
        except Exception:
            self._log.debug("wait.next_data.timeout")

        await asyncio.sleep(2)

        # Extract job data from __NEXT_DATA__
        jobs = await self._parse_next_data(page)

        if not jobs:
            # Fallback: DOM-based parsing
            html = await page.content()
            jobs = self._parse_html(html)

        await page.close()
        return jobs

    async def _parse_next_data(self, page: Any) -> list[Job]:
        """Extract jobs from Next.js __NEXT_DATA__ JSON in the page."""
        try:
            next_data_text = await page.eval_on_selector(
                "#__NEXT_DATA__", "el => el.textContent"
            )
            data = json.loads(next_data_text)
            raw_jobs = data.get("props", {}).get("pageProps", {}).get("jobs", [])
            self._log.info("next_data.jobs_found", count=len(raw_jobs))
            return self._parse_api(raw_jobs)
        except Exception:
            self._log.debug("next_data.parse_failed")
            return []

    def _parse_api(self, raw_jobs: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for item in raw_jobs:
            try:
                title = item.get("role", "") or item.get("title", "")
                company = item.get("companyName", "") or item.get("company", "")

                # location is a list e.g. ["Gurugram, Haryana, India"]
                location_raw = item.get("location", "")
                if isinstance(location_raw, list):
                    location = ", ".join(location_raw)
                else:
                    location = str(location_raw)

                # salary
                min_sal = item.get("minJdSalary")
                max_sal = item.get("maxJdSalary")
                currency = item.get("salaryCurrencyCode", "INR")
                if min_sal and max_sal:
                    salary = f"{min_sal} - {max_sal} {currency}"
                elif min_sal:
                    salary = f"{min_sal}+ {currency}"
                else:
                    salary = None

                # skills
                skills_raw = item.get("skills") or []
                if isinstance(skills_raw, list):
                    skills = [
                        (s.get("name", "") if isinstance(s, dict) else str(s)).strip()
                        for s in skills_raw
                    ]
                    skills = [s for s in skills if s]
                else:
                    skills = []

                # apply link — prefer jdLink (usually LinkedIn), else build from identifier
                apply_link = (
                    item.get("jdLink", "")
                    or item.get("careersPageLink", "")
                    or item.get("directJobLink", "")
                )
                if not apply_link:
                    jd_id = item.get("jdIdentifier", "")
                    if jd_id:
                        apply_link = f"https://jobs.weekday.works/jd/{jd_id}"

                # description (HTML)
                description = item.get("jobDetailsFromCompany", "") or ""

                # posted date
                posted_date = _parse_date(item.get("addedOn", ""))

                if title and company and apply_link:
                    jobs.append(
                        Job(
                            platform="weekday",
                            title=title.strip(),
                            company=company.strip(),
                            location=location.strip(),
                            salary=salary,
                            posted_date=posted_date,
                            skills=skills,
                            description=description,
                            apply_link=apply_link,
                        )
                    )
            except Exception:
                self._log.exception("api.parse_failed")
        return jobs

    def _parse_html(self, html: str) -> list[Job]:
        """Fallback: parse job links from the rendered DOM.

        Weekday uses styled-components with hashed class names, so we match
        on the link href pattern to jobs.weekday.works.
        """
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Every job has a named <a> link → the text is the job title
        job_links = soup.select('a[href*="jobs.weekday.works"]')
        self._log.info("html.job_links_found", count=len(job_links))

        seen: set[str] = set()
        for link in job_links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or href in seen:
                continue
            seen.add(href)

            # company name is encoded in the URL filter param:
            # ?filters={"companies":["airtel"]}
            company = ""
            m = re.search(r'"companies":\["([^"]+)"\]', href)
            if m:
                company = m.group(1).replace("-", " ").title()

            # location: look for the next text sibling nodes in the parent container
            parent = link.parent
            location = ""
            if parent:
                text = parent.get_text(" ", strip=True)
                # Pattern: "Title • Location • N Employees"
                parts = [p.strip() for p in text.split("•")]
                if len(parts) >= 2:
                    location = parts[1]

            if title:
                jobs.append(
                    Job(
                        platform="weekday",
                        title=title,
                        company=company,
                        location=location,
                        salary=None,
                        skills=[],
                        description="",
                        apply_link=href,
                    )
                )

        return jobs
