from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx
import structlog

from models.job import Job
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location, explain as explain_location

log = structlog.get_logger(__name__)

RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):
    """We Work Remotely scraper using their public RSS feeds."""

    name: str = "weworkremotely"
    requires_login: bool = False

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []
        pm_keywords = {"product manager", "product management", "senior pm",
                        "head of product", "director product", "vp product",
                        "product lead"}

        async with httpx.AsyncClient() as client:
            for feed_url in RSS_FEEDS:
                try:
                    self._log.info("rss.fetching", url=feed_url)
                    resp = await client.get(
                        feed_url,
                        headers={"User-Agent": "JobSearchAggregator/1.0"},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    jobs.extend(self._parse_rss(resp.text, pm_keywords))
                except Exception:
                    self._log.exception("rss.failed", url=feed_url)

        self._log.info("rss.done", total_pm_jobs=len(jobs))
        return jobs

    def _parse_rss(self, xml_text: str, pm_keywords: set[str]) -> list[Job]:
        jobs: list[Job] = []
        root = ET.fromstring(xml_text)

        for item in root.findall(".//item"):
            try:
                title = (item.findtext("title") or "").strip()
                if not any(kw in title.lower() for kw in pm_keywords):
                    continue

                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                # Clean HTML
                description = re.sub(r"<[^>]+>", " ", description)
                description = re.sub(r"\s+", " ", description).strip()

                pub_date = item.findtext("pubDate") or ""
                posted_date = None
                if pub_date:
                    try:
                        # RSS date format: "Tue, 01 Apr 2026 12:00:00 +0000"
                        dt = datetime.strptime(pub_date.strip(), "%a, %d %b %Y %H:%M:%S %z")
                        posted_date = dt.date()
                    except ValueError:
                        pass

                # Extract company from title (format: "Company: Job Title")
                company = ""
                if ":" in title:
                    parts = title.split(":", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                # Categories as skills
                skills = [cat.text for cat in item.findall("category") if cat.text]

                # Read the dedicated <region> element directly — as of Apr 2026 the
                # RSS feed exposes region as a first-class XML child of <item>, NOT
                # embedded in the <description> CDATA body.
                raw_region = (item.findtext("region") or "").strip()
                # Normalise to a location string the filter understands.
                if raw_region:
                    location = f"Remote — {raw_region}"
                else:
                    location = "Remote"

                if title and link:
                    # Reject region-restricted remotes that don't include India
                    if not is_acceptable_location(location):
                        self._log.debug("wwr.filtered_location",
                                        title=title, company=company,
                                        reason=explain_location(location))
                        continue
                    jobs.append(
                        Job(
                            platform="weworkremotely",
                            title=title,
                            company=company,
                            location=location,
                            posted_date=posted_date,
                            skills=skills,
                            description=description[:2000],
                            apply_link=link,
                        )
                    )
            except Exception:
                self._log.exception("rss.item_failed")

        return jobs
