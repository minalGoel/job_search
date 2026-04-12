from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urljoin

import httpx
import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page

from browser.context import BrowserManager
from models.job import Job
from mnc_careers.registry import MNC_REGISTRY, MNC
from services.location_filter import is_acceptable_location, explain as explain_location

log = structlog.get_logger(__name__)

PM_KEYWORDS = ["product manager", "product management", "senior pm", "group pm",
               "lead pm", "head of product", "director product", "vp product",
               "principal pm"]


class MNCCareerScraper:
    """Scrapes US MNC career pages for PM roles in Delhi NCR."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.bm = browser_manager
        self._log = log.bind(module="mnc_careers")

    async def scrape_all(self) -> list[Job]:
        """Scrape all MNC career pages that have pre-built PM search URLs."""
        all_jobs: list[Job] = []
        mncs_with_urls = [m for m in MNC_REGISTRY if m.pm_search_url]

        self._log.info("mnc.starting", count=len(mncs_with_urls))

        # Process in batches of 5 to avoid overloading
        for i in range(0, len(mncs_with_urls), 5):
            batch = mncs_with_urls[i:i + 5]
            tasks = [
                self._scrape_mnc_api(mnc) if mnc.api_url else self._scrape_mnc(mnc)
                for mnc in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for mnc, result in zip(batch, results):
                if isinstance(result, Exception):
                    self._log.error("mnc.failed", company=mnc.name, error=str(result))
                else:
                    all_jobs.extend(result)
                    self._log.info("mnc.scraped", company=mnc.name, jobs=len(result))

            await asyncio.sleep(3)

        return all_jobs

    async def _scrape_mnc(self, mnc: MNC) -> list[Job]:
        """Scrape a single MNC's career page for PM roles."""
        jobs: list[Job] = []
        page = None

        try:
            page = await self._get_page(mnc.pm_search_url)
            await asyncio.sleep(3)

            # Wait for content to load (many use React/Angular SPAs)
            try:
                await page.wait_for_selector(
                    "div[class*='job'], a[class*='job'], li[class*='job'], "
                    "div[class*='position'], div[class*='result'], tr[class*='job']",
                    timeout=12_000,
                )
            except Exception:
                self._log.debug("mnc.wait_timeout", company=mnc.name)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Job listing detection — ordered from most-specific to least-specific.
            # Excludes a[class*='position'] (matches 'position-absolute' skip-nav links)
            # and bare div[class*='card']/div[class*='listing'] (UI framework cards on
            # React SPAs like JPMorgan/Citi are NOT job entries — 78 false positives).
            listings = (
                soup.select("div[class*='job-result'], div[class*='job-card'], div[class*='job-tile'], div[class*='job-item']")
                or soup.select("div[class*='position-card'], div[class*='role-card']")
                or soup.select("a[class*='job']")
                or soup.select("li[class*='job'], li[class*='result']")
                or soup.select("tr[class*='job'], div[class*='posting'], div[class*='opening']")
                or soup.select("article")
            )
            # Filter out invisible/accessibility elements (sr-only skip links etc.)
            listings = [el for el in listings if el.get_text(strip=True)]

            self._log.info("mnc.listings_found", company=mnc.name, count=len(listings))

            for el in listings:
                try:
                    text = el.get_text(" ", strip=True).lower()

                    # Filter: must contain PM keyword
                    if not any(kw in text for kw in PM_KEYWORDS):
                        continue

                    # Extract title — structured elements first, anchor text as last resort
                    title_el = (
                        el.select_one("h2, h3, h4")
                        or el.select_one("a[class*='title'], span[class*='title'], div[class*='title']")
                        or el.select_one("[class*='job-title'], [class*='jobtitle'], [class*='role-title'], [class*='position-title']")
                        or el.select_one("a[href]")
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Extract link
                    link_el = el.select_one("a[href]") or (el if el.name == "a" else None)
                    href = link_el.get("href", "") if link_el else ""
                    if href and not href.startswith("http"):
                        href = urljoin(mnc.pm_search_url, href)

                    # Extract location — expanded selector set + fallback to registry value.
                    loc_el = (
                        el.select_one("span[class*='location'], div[class*='location'], span[class*='loc']")
                        or el.select_one("li[class*='location'], p[class*='location']")
                        or el.select_one("[data-testid*='location'], [data-automation*='location']")
                        or el.select_one("[class*='city'], [class*='region'], [class*='country']")
                        or el.select_one("[class*='job-location'], [class*='jobLocation']")
                        or el.select_one("span[class*='meta'], div[class*='meta']")
                    )
                    location = loc_el.get_text(strip=True) if loc_el else ""
                    # Fallback: pm_search_url already filters for India, so trust the registry
                    if not location and mnc.delhi_ncr_office:
                        location = mnc.delhi_ncr_office
                        self._log.debug("mnc.location_fallback", company=mnc.name, fallback=location)

                    if not (title and href):
                        continue

                    # Reject jobs outside Delhi NCR / global remote
                    if not is_acceptable_location(location):
                        self._log.debug("mnc.filtered_location",
                                        company=mnc.name, title=title,
                                        reason=explain_location(location))
                        continue

                    jobs.append(
                        Job(
                            platform=f"mnc_{mnc.name.lower().replace(' ', '_').replace('/', '_')}",
                            title=title,
                            company=mnc.name,
                            location=location,
                            apply_link=href,
                            description=f"Direct from {mnc.name} careers page",
                        )
                    )
                except Exception:
                    self._log.exception("mnc.listing_failed", company=mnc.name)

        except Exception:
            self._log.exception("mnc.page_failed", company=mnc.name)
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

        return jobs

    async def _scrape_mnc_api(self, mnc: MNC) -> list[Job]:
        """Fetch jobs via JSON API (no Playwright).

        Supported api_type values:
          "amazon_jobs"  — Amazon Jobs JSON endpoint
          "greenhouse"   — Greenhouse boards-api (boards-api.greenhouse.io/v1/boards/{id}/jobs)
          "lever"        — Lever public postings API (api.lever.co/v0/postings/{slug}?mode=json)
        """
        jobs: list[Job] = []
        platform = f"mnc_{mnc.name.lower().replace(' ', '_').replace('/', '_')}"
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
                timeout=20,
            ) as client:
                resp = await client.get(mnc.api_url)
                resp.raise_for_status()
                data = resp.json()

            if mnc.api_type == "amazon_jobs":
                for job in data.get("jobs", []):
                    title = job.get("title", "")
                    location = job.get("location", "")
                    job_path = job.get("job_path", "")
                    href = f"https://www.amazon.jobs{job_path}" if job_path else ""

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in PM_KEYWORDS):
                        continue
                    if not (title and href):
                        continue
                    if not location and mnc.delhi_ncr_office:
                        location = mnc.delhi_ncr_office
                    if not is_acceptable_location(location):
                        self._log.debug("mnc.filtered_location", company=mnc.name,
                                        title=title, reason=explain_location(location))
                        continue
                    jobs.append(Job(
                        platform=platform,
                        title=title,
                        company=mnc.name,
                        location=location or mnc.delhi_ncr_office,
                        apply_link=href,
                        description=job.get("description_short", f"Direct from {mnc.name} careers page"),
                    ))

            elif mnc.api_type == "greenhouse":
                # Greenhouse boards-api returns {"jobs": [...], "meta": {...}}
                # Each job: {"id", "title", "location": {"name"}, "absolute_url", "content"}
                for job in data.get("jobs", []):
                    title = job.get("title", "")
                    location = (job.get("location") or {}).get("name", "")
                    href = job.get("absolute_url", "")
                    description = job.get("content", "") or f"Direct from {mnc.name} careers page"
                    # strip HTML tags from Greenhouse content
                    import re as _re
                    description = _re.sub(r"<[^>]+>", " ", description)[:500]

                    if not any(kw in title.lower() for kw in PM_KEYWORDS):
                        continue
                    if not (title and href):
                        continue
                    if not location:
                        location = mnc.delhi_ncr_office
                    if not is_acceptable_location(location):
                        self._log.debug("mnc.filtered_location", company=mnc.name,
                                        title=title, reason=explain_location(location))
                        continue
                    jobs.append(Job(
                        platform=platform,
                        title=title,
                        company=mnc.name,
                        location=location or mnc.delhi_ncr_office,
                        apply_link=href,
                        description=description,
                    ))

            elif mnc.api_type == "lever":
                # Lever public API returns a JSON array of postings
                # Each posting: {"text": title, "categories": {"location": "..."}, "hostedUrl": url, "descriptionPlain": desc}
                postings = data if isinstance(data, list) else data.get("data", [])
                for job in postings:
                    title = job.get("text", "")
                    categories = job.get("categories") or {}
                    location = categories.get("location", "") or categories.get("team", "")
                    href = job.get("hostedUrl", "") or job.get("applyUrl", "")
                    description = (job.get("descriptionPlain") or "")[:500]

                    if not any(kw in title.lower() for kw in PM_KEYWORDS):
                        continue
                    if not (title and href):
                        continue
                    if not location:
                        location = mnc.delhi_ncr_office
                    if not is_acceptable_location(location):
                        self._log.debug("mnc.filtered_location", company=mnc.name,
                                        title=title, reason=explain_location(location))
                        continue
                    jobs.append(Job(
                        platform=platform,
                        title=title,
                        company=mnc.name,
                        location=location or mnc.delhi_ncr_office,
                        apply_link=href,
                        description=description or f"Direct from {mnc.name} careers page",
                    ))

            self._log.info("mnc.api_scraped", company=mnc.name, jobs=len(jobs))
        except Exception:
            self._log.exception("mnc.api_failed", company=mnc.name)
        return jobs

    async def _get_page(self, url: str) -> Page:
        context = await self.bm.get_context("mnc_careers", Path("cookies"))
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            await page.close()
            raise
        return page
