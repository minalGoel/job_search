from __future__ import annotations

import asyncio
import re

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page

from browser.context import BrowserManager
from models.job import Job
from mnc_careers.registry import MNC_REGISTRY, MNC

log = structlog.get_logger(__name__)

PM_KEYWORDS = ["product manager", "product management", "senior pm", "group pm",
               "lead pm", "head of product", "director product", "vp product",
               "principal pm"]
LOCATION_KEYWORDS = ["delhi", "ncr", "gurugram", "gurgaon", "noida", "india", "remote"]


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
            tasks = [self._scrape_mnc(mnc) for mnc in batch]
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

            # Generic job listing detection
            listings = (
                soup.select("div[class*='job-result'], div[class*='job-card']")
                or soup.select("a[class*='job'], a[class*='position']")
                or soup.select("li[class*='job'], li[class*='result']")
                or soup.select("tr[class*='job'], div[class*='posting']")
                or soup.select("div[class*='card'], div[class*='listing']")
                or soup.select("article")
            )

            self._log.info("mnc.listings_found", company=mnc.name, count=len(listings))

            for el in listings:
                try:
                    text = el.get_text(" ", strip=True).lower()

                    # Filter: must contain PM keyword
                    if not any(kw in text for kw in PM_KEYWORDS):
                        continue

                    # Extract title
                    title_el = el.select_one(
                        "h2, h3, h4, a[class*='title'], "
                        "span[class*='title'], div[class*='title']"
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Extract link
                    link_el = el.select_one("a[href]") or (el if el.name == "a" else None)
                    href = link_el.get("href", "") if link_el else ""
                    if href and not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(mnc.pm_search_url, href)

                    # Extract location
                    loc_el = el.select_one(
                        "span[class*='location'], div[class*='location'], "
                        "span[class*='loc']"
                    )
                    location = loc_el.get_text(strip=True) if loc_el else mnc.delhi_ncr_office

                    if not (title and href):
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

            await page.close()
        except Exception:
            self._log.exception("mnc.page_failed", company=mnc.name)

        return jobs

    async def _get_page(self, url: str) -> Page:
        from pathlib import Path
        context = await self.bm.get_context("mnc_careers", Path("cookies"))
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return page
