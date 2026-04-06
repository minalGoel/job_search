from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

PAGE_SIZE = 20
MAX_PAGES = 5  # 5 × 20 = 100 max (total is usually ~88)

_BASE_URL = "https://www.instahyre.com/api/v1/job_search"
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.instahyre.com/search-jobs/",
}
_COOKIES_FILE = Path("cookies") / "instahyre.json"


class InstahyreScraper(BaseScraper):
    """Instahyre scraper — uses the private JSON API with session cookies.

    Instahyre is a profile-matching platform. The API endpoint
    ``/api/v1/job_search`` accepts ``skills`` and ``jobLocations`` filters.
    Credentials are loaded from ``cookies/instahyre.json`` (same file used
    for Playwright sessions).
    """

    name: str = "instahyre"
    requires_login: bool = True

    def _load_cookies(self) -> dict[str, str]:
        """Load session cookies from the Playwright storage state file."""
        try:
            data = json.loads(_COOKIES_FILE.read_text())
            return {
                c["name"]: c["value"]
                for c in data.get("cookies", [])
                if "instahyre" in c.get("domain", "")
            }
        except Exception:
            self._log.debug("cookies.load_failed", path=str(_COOKIES_FILE))
            return {}

    async def scrape(self) -> list[Job]:
        cookies = self._load_cookies()
        if not cookies.get("sessionid"):
            self._log.warning("session.expired", msg="No sessionid in instahyre.json")
            return []

        all_jobs: list[Job] = []
        async with httpx.AsyncClient(
            headers=_BASE_HEADERS, cookies=cookies, timeout=20, follow_redirects=True
        ) as client:
            for page_num in range(MAX_PAGES):
                params = {
                    "isLandingPage": "true",
                    "jobLocations": "Delhi / NCR",
                    "skills": "product management",
                    "job_type": 0,
                    "source": "opportunities",
                    "offset": page_num * PAGE_SIZE,
                    "limit": PAGE_SIZE,
                }
                url = f"{_BASE_URL}?{urlencode(params)}"
                self._log.info("api.fetching", page=page_num, url=url)
                try:
                    resp = await client.get(url)
                    if resp.status_code == 401:
                        self._log.warning("session.expired", status=401)
                        break
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    self._log.exception("api.request_failed", page=page_num)
                    break

                raw_jobs: list[dict[str, Any]] = data.get("objects", [])
                meta: dict[str, Any] = data.get("meta", {})

                if not raw_jobs:
                    self._log.info("api.empty_page", page=page_num)
                    break

                self._log.info(
                    "api.page_received",
                    page=page_num,
                    count=len(raw_jobs),
                    total=meta.get("total_count"),
                )

                parsed = self._parse_jobs(raw_jobs)
                all_jobs.extend(parsed)
                self._log.info("api.page_parsed", page=page_num, parsed=len(parsed))

                if not meta.get("next"):
                    break
                await asyncio.sleep(1)

        return all_jobs

    def _parse_jobs(self, raw_jobs: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for item in raw_jobs:
            try:
                title = item.get("title", "").strip()

                employer = item.get("employer") or {}
                company = employer.get("company_name", "").strip() if isinstance(employer, dict) else ""

                location = item.get("locations", "")
                if isinstance(location, list):
                    location = ", ".join(str(l) for l in location)

                # Skills from keywords list
                keywords = item.get("keywords", []) or []
                skills = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]

                apply_link = item.get("public_url", "")
                if apply_link and not apply_link.startswith("http"):
                    apply_link = f"https://www.instahyre.com{apply_link}"

                if title and company and apply_link:
                    jobs.append(
                        Job(
                            platform="instahyre",
                            title=title,
                            company=company,
                            location=str(location).strip(),
                            salary=None,  # Instahyre doesn't expose salary in listings
                            posted_date=None,
                            skills=skills,
                            description="",
                            apply_link=apply_link,
                        )
                    )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs
