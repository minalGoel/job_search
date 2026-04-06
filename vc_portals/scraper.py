from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page

from browser.context import BrowserManager
from models.job import Job
from vc_portals.registry import VC_REGISTRY, VCFund

log = structlog.get_logger(__name__)

PM_KEYWORDS = ["product manager", "product management", "senior pm", "group pm",
               "lead pm", "head of product", "director product", "vp product"]
LOCATION_KEYWORDS = ["delhi", "ncr", "gurugram", "gurgaon", "noida", "india", "remote"]


class VCPortalScraper:
    """Scrapes VC job portals and their portfolio company career pages for PM roles."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.bm = browser_manager
        self._log = log.bind(module="vc_portals")

    async def scrape_all(self) -> list[Job]:
        """Scrape all VC portals with known URLs."""
        all_jobs: list[Job] = []
        vcs_with_portals = [vc for vc in VC_REGISTRY if vc.job_portal_url]

        self._log.info("vc.starting", count=len(vcs_with_portals))

        for vc in vcs_with_portals:
            try:
                jobs = await self._scrape_vc_portal(vc)
                all_jobs.extend(jobs)
                self._log.info("vc.scraped", vc=vc.name, jobs=len(jobs))
                await asyncio.sleep(2)
            except Exception:
                self._log.exception("vc.failed", vc=vc.name)

        return all_jobs

    async def _scrape_vc_portal(self, vc: VCFund) -> list[Job]:
        """Scrape a single VC's job portal for PM roles."""
        jobs: list[Job] = []
        page = await self._get_page(vc.job_portal_url)
        await asyncio.sleep(2)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Generic job listing selectors (works for most portals)
        job_elements = (
            soup.select("div[class*='job'], div[class*='posting'], div[class*='position']")
            or soup.select("tr[class*='job'], li[class*='job'], a[class*='job']")
            or soup.select("div[class*='card'], div[class*='listing']")
            or soup.select("article")
        )

        self._log.info("vc.listings_found", vc=vc.name, count=len(job_elements))

        for el in job_elements:
            try:
                text = el.get_text(strip=True).lower()

                # Filter for PM roles
                if not any(kw in text for kw in PM_KEYWORDS):
                    continue

                # Extract title
                title_el = el.select_one("h2, h3, h4, a[class*='title'], div[class*='title'], span[class*='title']")
                title = title_el.get_text(strip=True) if title_el else ""

                # Extract link
                link_el = el.select_one("a[href]") or (el if el.name == "a" else None)
                href = link_el.get("href", "") if link_el else ""
                if href and not href.startswith("http"):
                    # Build absolute URL from portal base
                    from urllib.parse import urljoin
                    href = urljoin(vc.job_portal_url, href)

                # Extract company (for portfolio job boards, company is in the listing)
                company_el = el.select_one(
                    "span[class*='company'], div[class*='company'], "
                    "span[class*='dept'], div[class*='department']"
                )
                company = company_el.get_text(strip=True) if company_el else vc.name

                # Extract location
                loc_el = el.select_one(
                    "span[class*='location'], div[class*='location'], "
                    "span[class*='loc']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                if not (title and href):
                    continue

                jobs.append(
                    Job(
                        platform=f"vc_{vc.name.lower().replace(' ', '_')}",
                        title=title,
                        company=company,
                        location=location,
                        apply_link=href,
                        description=f"Via {vc.name} portfolio job board",
                    )
                )
            except Exception:
                self._log.exception("vc.listing_parse_failed", vc=vc.name)

        await page.close()
        return jobs

    async def _get_page(self, url: str) -> Page:
        from pathlib import Path
        context = await self.bm.get_context("vc_portals", Path("cookies"))
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return page
