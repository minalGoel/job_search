from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from models.job import Job
from scrapers.api_base import parse_epoch
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location

log = structlog.get_logger(__name__)

# Delhi NCR location ID on IIMJobs
# 1 = Delhi NCR (includes Delhi, Noida, Gurgaon/Gurugram)
DELHI_NCR_LOC_ID = 1
PAGE_SIZE = 50
MAX_PAGES = 3  # 3 × 50 = 150 jobs max

_BASE_URL = "https://gladiator.iimjobs.com/job/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.iimjobs.com/",
}


class IIMJobsScraper(BaseScraper):
    """IIMJobs scraper — uses the public gladiator.iimjobs.com REST API.

    Identical structure to the Hirist scraper (same parent company).
    No login or Playwright needed.
    """

    name: str = "iimjobs"
    requires_login: bool = False
    uses_browser: bool = False

    async def scrape(self) -> list[Job]:
        all_jobs: list[Job] = []
        # Pull the configured search query from SearchParams so we stay
        # consistent with the rest of the pipeline. Fall back to a safe
        # default if the param list is empty.
        keywords = getattr(self.search_params, "title_keywords", None) or ["product manager"]
        query = keywords[0]
        async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
            for page_num in range(MAX_PAGES):
                params = {
                    "query": query,
                    "page": page_num,
                    "loc": DELHI_NCR_LOC_ID,
                    "posting": 0,
                    "industry": "",
                }
                url = f"{_BASE_URL}?{urlencode(params)}"
                self._log.info("api.fetching", page=page_num, url=url)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    self._log.exception("api.request_failed", page=page_num)
                    break

                raw_jobs: list[dict[str, Any]] = data.get("data", [])
                if not raw_jobs:
                    self._log.info("api.empty_page", page=page_num)
                    break

                self._log.info(
                    "api.page_received",
                    page=page_num,
                    count=len(raw_jobs),
                    total=data.get("totalJobs"),
                )

                parsed = self._parse_jobs(raw_jobs)
                all_jobs.extend(parsed)
                self._log.info("api.page_parsed", page=page_num, parsed=len(parsed))

                if not data.get("hasMore", False):
                    break
                await asyncio.sleep(1)

        return all_jobs

    def _parse_jobs(self, raw_jobs: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for item in raw_jobs:
            try:
                title = item.get("jobdesignation", "") or item.get("title", "")

                company_data = item.get("companyData") or {}
                company = (
                    company_data.get("companyName", "")
                    if isinstance(company_data, dict)
                    else str(company_data)
                )

                # Locations: list of {id, name}
                locations_raw = item.get("location") or item.get("locations") or []
                location_names = [
                    loc.get("name", "") if isinstance(loc, dict) else str(loc)
                    for loc in locations_raw
                ]
                location = ", ".join(ln for ln in location_names if ln)

                # Salary
                min_sal = item.get("minSal", 0) or 0
                max_sal = item.get("maxSal", 0) or 0
                hide_sal = item.get("hideSal", False)
                if hide_sal or (min_sal == 0 and max_sal == 0):
                    salary = None
                else:
                    salary = f"{min_sal} - {max_sal} LPA"

                # Skills from tags: [{id, name, isMandatory}]
                tags = item.get("tags", []) or []
                skills = [
                    t.get("name", "") if isinstance(t, dict) else str(t)
                    for t in tags
                ]
                skills = [s.strip() for s in skills if s.strip()]

                # Apply link
                apply_link = item.get("jobDetailUrl", "") or item.get("applyUrl", "")
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://www.iimjobs.com{apply_link}"

                # Posted date (createdTimeMs is Unix ms; createdTime may be s)
                # createdTime may be seconds or ms depending on the field —
                # parse_epoch decides by magnitude (known_edge_cases: V-13).
                posted_date: date | None = parse_epoch(
                    item.get("createdTimeMs") or item.get("createdTime")
                )

                if title and company and apply_link:
                    if not is_acceptable_location(location):
                        self._log.debug("item.location_rejected", title=title, location=location)
                        continue
                    jobs.append(
                        Job(
                            platform="iimjobs",
                            title=title.strip(),
                            company=company.strip(),
                            location=location,
                            salary=salary,
                            posted_date=posted_date,
                            skills=skills,
                            description="",
                            apply_link=apply_link,
                        )
                    )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs
