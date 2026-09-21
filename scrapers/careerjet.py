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

API_URL = "https://public.api.careerjet.net/search"
PAGE_SIZE = 99
MAX_PAGES_PER_LOCATION = 2
_IP_LOOKUP = "https://api.ipify.org"


class CareerjetScraper(APIScraper):
    """Careerjet aggregator — public search API (free affiliate id).

    The API requires ``affid``, ``user_ip``, ``user_agent`` and ``url``
    (referer) on every call or it answers ``type: ERROR``. Location variants
    are only a coarse pre-filter; a ``type: LOCATIONS`` answer means the
    variant was ambiguous and is skipped. Skipped while ``CAREERJET_AFFID``
    is blank.
    """

    name: str = "careerjet"
    required_settings = ("CAREERJET_AFFID",)

    async def _user_ip(self, client: httpx.AsyncClient) -> str:
        try:
            resp = await client.get(_IP_LOOKUP, timeout=5)
            if resp.status_code == 200 and resp.text.strip():
                return resp.text.strip()
        except Exception:
            pass
        self._log.warning("api.user_ip_fallback", note="ipify unreachable; using 127.0.0.1")
        return "127.0.0.1"

    async def scrape(self) -> list[Job]:
        self._require_settings()
        keywords = list(getattr(self.search_params, "title_keywords", None) or ["product manager"])
        locations = list(getattr(self.search_params, "location_variants", None) or ["Delhi NCR"])
        jobs: list[Job] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(headers=self.HEADERS, timeout=25, follow_redirects=True) as client:
            user_ip = await self._user_ip(client)
            for keyword in keywords:
                for location in locations:
                    for page in range(1, MAX_PAGES_PER_LOCATION + 1):
                        params = {
                            "locale_code": "en_IN",
                            "keywords": keyword,
                            "location": location,
                            "pagesize": PAGE_SIZE,
                            "page": page,
                            "sort": "date",
                            "affid": self.settings.CAREERJET_AFFID,
                            "user_ip": user_ip,
                            "user_agent": self.HEADERS["User-Agent"],
                            "url": "https://public.api.careerjet.net/",
                        }
                        self._log.info("api.fetching", keyword=keyword, location=location, page=page)
                        resp = await client.get(API_URL, params=params)
                        if resp.status_code in (401, 403):
                            raise ScraperSkipped(f"API key rejected ({resp.status_code})")
                        resp.raise_for_status()
                        data = resp.json()
                        kind = data.get("type", "")
                        if kind == "LOCATIONS":
                            self._log.info(
                                "api.ambiguous_location", location=location,
                                options=[l.get("name") for l in data.get("solveLocations", []) or []][:5],
                            )
                            break
                        if kind == "ERROR":
                            err = str(data.get("error", "unknown error"))
                            if "affid" in err.lower():
                                raise ScraperSkipped(f"affid rejected: {err}")
                            raise RuntimeError(f"careerjet: {err}")
                        items = data.get("jobs", []) or []
                        pages = int(data.get("pages", 1) or 1)
                        self._log.info("api.page_received", page=page, count=len(items), pages=pages)
                        if not items:
                            break
                        for job in self._parse_results(items):
                            key = stable_link(job.apply_link)
                            if key not in seen:
                                seen.add(key)
                                jobs.append(job)
                        if page >= pages:
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
                location = strip_html(item.get("locations", "") or "")
                apply_link = item.get("url", "") or ""
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
                        id=stable_job_id("careerjet", company, title, apply_link),
                        platform="careerjet",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=parse_iso_date(item.get("date")),
                        skills=[],
                        description=strip_html(item.get("description", ""))[:2000],
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("parse_item_failed")
        return jobs
