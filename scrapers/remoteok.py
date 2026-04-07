from __future__ import annotations

import re
from datetime import date, datetime

import httpx
import structlog

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


class RemoteOKScraper(BaseScraper):
    """RemoteOK scraper using their free public JSON API."""

    name: str = "remoteok"
    requires_login: bool = False

    async def scrape(self) -> list[Job]:
        api_url = "https://remoteok.com/api"
        self._log.info("api.fetching", url=api_url)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                api_url,
                headers={"User-Agent": "JobSearchAggregator/1.0"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        # First item is usually a "legal" disclaimer; skip it
        listings = data[1:] if isinstance(data, list) and len(data) > 1 else data

        jobs: list[Job] = []
        pm_keywords = {"product manager", "product management", "senior pm",
                        "head of product", "director product", "vp product"}

        for item in listings:
            try:
                position = item.get("position", "")
                if not any(kw in position.lower() for kw in pm_keywords):
                    continue

                company = item.get("company", "")
                location = item.get("location", "Remote")
                salary_min = item.get("salary_min")
                salary_max = item.get("salary_max")
                salary = f"${salary_min} - ${salary_max}" if salary_min is not None and salary_max is not None else None

                tags = item.get("tags", [])
                if isinstance(tags, list):
                    skills = tags
                else:
                    skills = []

                # Prefer the employer's direct apply URL; fall back to the RemoteOK
                # listing page only if apply_url is absent.
                apply_url = item.get("apply_url", "") or item.get("url", "")
                if apply_url and not apply_url.startswith("http"):
                    apply_url = f"https://remoteok.com{apply_url}"

                description = item.get("description", "")
                # Clean HTML from description
                description = re.sub(r"<[^>]+>", " ", description)
                description = re.sub(r"\s+", " ", description).strip()

                date_str = item.get("date", "")
                posted_date = None
                if date_str:
                    try:
                        posted_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                    except ValueError:
                        pass

                if position and company:
                    final_location = location.strip() if location else "Remote"
                    # Reject region-restricted remotes that don't include India
                    from services.location_filter import is_acceptable_location, explain as explain_location
                    if not is_acceptable_location(final_location):
                        self._log.debug("remoteok.filtered_location",
                                        title=position, company=company,
                                        reason=explain_location(final_location))
                        continue
                    jobs.append(
                        Job(
                            platform="remoteok",
                            title=position.strip(),
                            company=company.strip(),
                            location=final_location,
                            salary=salary,
                            posted_date=posted_date,
                            skills=skills,
                            description=description[:2000],
                            apply_link=apply_url,
                        )
                    )
            except Exception:
                self._log.exception("api.item_failed")

        self._log.info("api.done", total_listings=len(listings), pm_jobs=len(jobs))
        return jobs
