from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from models.job import Job
from scrapers.api_base import APIScraper, parse_iso_date, stable_job_id, stable_link, strip_html
from scrapers.base import ScraperSkipped
from services.location_filter import is_acceptable_location, explain as explain_location
from services.title_filter import is_relevant_title, explain_title

log = structlog.get_logger(__name__)

API_URL = "https://jooble.org/api/{key}"
MAX_PAGES_PER_LOCATION = 3


class JoobleScraper(APIScraper):
    """Jooble aggregator — POST JSON API (free key issued by email).

    Loops keyword × ``SearchParams.location_variants`` as a coarse pre-filter
    (≤ 18 requests), dedupes by stable link, and applies the local title and
    location filters to every item. Skipped while ``JOOBLE_API_KEY`` is blank.
    """

    name: str = "jooble"
    required_settings = ("JOOBLE_API_KEY",)

    async def scrape(self) -> list[Job]:
        self._require_settings()
        keywords = list(getattr(self.search_params, "title_keywords", None) or ["product manager"])
        locations = list(getattr(self.search_params, "location_variants", None) or ["Delhi NCR"])
        url = API_URL.format(key=self.settings.JOOBLE_API_KEY)
        jobs: list[Job] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(headers=self.HEADERS, timeout=25) as client:
            for keyword in keywords:
                for location in locations:
                    for page in range(1, MAX_PAGES_PER_LOCATION + 1):
                        payload = {"keywords": keyword, "location": location, "page": str(page)}
                        self._log.info("api.fetching", keyword=keyword, location=location, page=page)
                        resp = await client.post(url, json=payload)
                        if resp.status_code in (401, 403):
                            raise ScraperSkipped(f"API key rejected ({resp.status_code})")
                        resp.raise_for_status()
                        data = resp.json()
                        items = data.get("jobs", []) or []
                        total = data.get("totalCount", 0) or 0
                        self._log.info("api.page_received", page=page, count=len(items), total=total)
                        if not items:
                            break
                        for job in self._parse_results(items):
                            key = stable_link(job.apply_link)
                            if key not in seen:
                                seen.add(key)
                                jobs.append(job)
                        if page * len(items) >= total:
                            break
                        await asyncio.sleep(1)
        self._log.info("api.done", jobs=len(jobs))
        return jobs

    def _parse_results(self, items: list[dict[str, Any]]) -> list[Job]:
        jobs: list[Job] = []
        for item in items:
            try:
                title = strip_html(item.get("title", ""))
                company = strip_html(item.get("company", "") or "")
                location = strip_html(item.get("location", "") or "")
                apply_link = item.get("link", "") or ""
                # An empty company would make dedup_hash collide across every
                # same-title job in the region — skip rather than default.
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
                salary = strip_html(item.get("salary", "") or "") or None
                jobs.append(
                    Job(
                        id=stable_job_id("jooble", company, title, apply_link),
                        platform="jooble",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=parse_iso_date(item.get("updated")),
                        skills=[],
                        description=strip_html(item.get("snippet", ""))[:2000],
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs
