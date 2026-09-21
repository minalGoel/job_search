from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from models.job import Job
from scrapers.api_base import (
    APIScraper,
    format_inr_salary,
    parse_iso_date,
    stable_job_id,
    strip_html,
)
from scrapers.base import ScraperSkipped
from services.location_filter import is_acceptable_location, explain as explain_location
from services.title_filter import is_relevant_title, explain_title

log = structlog.get_logger(__name__)

API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 10
MAX_DAYS_OLD = 30


class AdzunaScraper(APIScraper):
    """Adzuna India aggregator — public JSON API (free key).

    Fetches India-wide (no ``where`` filter — location is decided locally by
    ``is_acceptable_location``) with ``title_only=<keyword>`` as a coarse
    volume pre-filter; ``is_relevant_title`` remains authoritative.
    Skipped (not failed) while ``ADZUNA_APP_ID``/``ADZUNA_APP_KEY`` are blank.
    """

    name: str = "adzuna"
    required_settings = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")

    async def scrape(self) -> list[Job]:
        self._require_settings()
        keywords = list(getattr(self.search_params, "title_keywords", None) or ["product manager"])
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(headers=self.HEADERS, timeout=25, follow_redirects=True) as client:
            for keyword in keywords:
                for page in range(1, MAX_PAGES + 1):
                    params = {
                        "app_id": self.settings.ADZUNA_APP_ID,
                        "app_key": self.settings.ADZUNA_APP_KEY,
                        "results_per_page": RESULTS_PER_PAGE,
                        "title_only": keyword,
                        "max_days_old": MAX_DAYS_OLD,
                        "sort_by": "date",
                        "content-type": "application/json",
                    }
                    url = API_URL.format(page=page)
                    self._log.info("api.fetching", page=page, keyword=keyword, url=url)
                    resp = await client.get(url, params=params)
                    if resp.status_code in (401, 403):
                        raise ScraperSkipped(f"API key rejected ({resp.status_code})")
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", []) or []
                    total = data.get("count", 0) or 0
                    self._log.info("api.page_received", page=page, count=len(results), total=total)
                    if not results:
                        break
                    for job in self._parse_results(results):
                        if job.id not in seen_ids:
                            seen_ids.add(job.id)
                            jobs.append(job)
                    # Advance by what was actually returned — never by the requested page size.
                    if len(results) < RESULTS_PER_PAGE or page * RESULTS_PER_PAGE >= total:
                        break
                    await asyncio.sleep(1)
        self._log.info("api.done", jobs=len(jobs))
        return jobs

    def _parse_results(self, results: list[dict[str, Any]]) -> list[Job]:
        """Pure: JSON items → Job list (title + location filtered locally)."""
        jobs: list[Job] = []
        for item in results:
            try:
                title = strip_html(item.get("title", ""))  # matched words come wrapped in <strong>
                company = strip_html(((item.get("company") or {}).get("display_name")) or "")
                loc = item.get("location") or {}
                location = loc.get("display_name") or ", ".join(loc.get("area", []) or [])
                apply_link = item.get("redirect_url", "") or ""
                if not (title and company and apply_link):
                    continue
                if not is_relevant_title(title):
                    self._log.debug("item.title_rejected", title=title, reason=explain_title(title))
                    continue
                if not is_acceptable_location(location):
                    self._log.debug(
                        "item.location_rejected", title=title, company=company,
                        location=location, reason=explain_location(location),
                    )
                    continue
                salary = format_inr_salary(
                    item.get("salary_min"), item.get("salary_max"),
                    predicted=str(item.get("salary_is_predicted", "0")) == "1",
                )
                jobs.append(
                    Job(
                        # Raw redirect_url is kept (it needs its query params to
                        # resolve); the id is computed over the stable part so
                        # per-request tracking tokens don't churn it.
                        id=stable_job_id("adzuna", company, title, apply_link),
                        platform="adzuna",
                        title=title,
                        company=company,
                        location=location.strip(),
                        salary=salary,
                        posted_date=parse_iso_date(item.get("created")),
                        skills=[],
                        description=strip_html(item.get("description", ""))[:2000],
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs
