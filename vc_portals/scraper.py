from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page, Response

from browser.context import BrowserManager
from models.job import Job
from vc_portals.registry import VC_REGISTRY, VCFund

log = structlog.get_logger(__name__)

PM_KEYWORDS = [
    "product manager", "product management", "senior pm", "group pm",
    "lead pm", "head of product", "director of product", "director product",
    "vp product", "chief product", "associate pm", "founding pm",
    "principal pm", "staff pm",
]
LOCATION_KEYWORDS = ["delhi", "ncr", "gurugram", "gurgaon", "noida", "india", "remote", "anywhere"]


def _is_pm_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in PM_KEYWORDS)


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
        """Scrape a single VC's job portal — tries JSON API interception first, then HTML."""
        captured_api: list[dict] = []

        async def _intercept(response: Response) -> None:
            url = response.url
            ct = response.headers.get("content-type", "")
            if response.status == 200 and "json" in ct:
                try:
                    body = await response.json()
                    if isinstance(body, dict) and (
                        body.get("jobs") or body.get("data") or body.get("results")
                        or body.get("postings") or body.get("positions")
                    ):
                        captured_api.append(body)
                except Exception:
                    pass

        page = await self._get_page(vc.job_portal_url, _intercept)
        await asyncio.sleep(3)

        # Try typing "product manager" into any search/title input to trigger filtered results
        for selector in [
            'input[placeholder*="title"]', 'input[placeholder*="Title"]',
            'input[placeholder*="search"]', 'input[placeholder*="Search"]',
            'input[placeholder*="role"]', 'input[placeholder*="Role"]',
            'input[type="search"]',
        ]:
            try:
                inp = await page.query_selector(selector)
                if inp:
                    await inp.fill("product manager")
                    await asyncio.sleep(3)
                    self._log.debug("vc.search_typed", vc=vc.name, selector=selector)
                    break
            except Exception:
                pass

        jobs: list[Job] = []

        # --- Strategy 1: JSON API ---
        if captured_api:
            jobs = self._parse_api_responses(captured_api, vc)
            self._log.info("vc.api_parsed", vc=vc.name, jobs=len(jobs))

        # --- Strategy 2: HTML fallback ---
        if not jobs:
            html = await page.content()
            jobs = self._parse_html(html, vc)
            self._log.info("vc.html_parsed", vc=vc.name, jobs=len(jobs))

        await page.close()
        return jobs

    def _parse_api_responses(self, responses: list[dict], vc: VCFund) -> list[Job]:
        jobs: list[Job] = []
        for resp in responses:
            items = (
                resp.get("jobs", [])
                or resp.get("data", [])
                or resp.get("results", [])
                or resp.get("postings", [])
                or resp.get("positions", [])
                or []
            )
            if isinstance(items, dict):
                items = list(items.values())

            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    title = (
                        item.get("title", "")
                        or item.get("name", "")
                        or item.get("jobTitle", "")
                    ).strip()

                    if not _is_pm_role(title):
                        continue

                    company = (
                        item.get("companyName", "")
                        or item.get("company", "")
                        or item.get("organization", "")
                        or vc.name
                    ).strip()

                    # Locations
                    loc_raw = item.get("locations", item.get("location", item.get("normalizedLocations", "")))
                    if isinstance(loc_raw, list):
                        location = ", ".join(str(l) for l in loc_raw if l)
                    else:
                        location = str(loc_raw or "")

                    # Apply link
                    apply_link = (
                        item.get("applyUrl", "")
                        or item.get("url", "")
                        or item.get("hostedUrl", "")
                        or item.get("absoluteUrl", "")
                        or item.get("jobUrl", "")
                    )
                    if apply_link and not apply_link.startswith("http"):
                        apply_link = urljoin(vc.job_portal_url, apply_link)

                    if not (title and apply_link):
                        continue

                    jobs.append(Job(
                        platform=f"vc_{vc.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}",
                        title=title,
                        company=company,
                        location=location,
                        salary=None,
                        skills=[],
                        description=f"Via {vc.name} portfolio",
                        apply_link=apply_link,
                    ))
                except Exception:
                    self._log.exception("vc.api_item_failed", vc=vc.name)
        return jobs

    def _parse_html(self, html: str, vc: VCFund) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Look for any links that could be job postings
        job_links = (
            soup.select("a[href*='/jobs/'], a[href*='/job/'], a[href*='/careers/'], "
                        "a[href*='/opening/'], a[href*='/posting/']")
        )

        for link in job_links:
            try:
                title = link.get_text(strip=True)
                if not title or not _is_pm_role(title):
                    continue

                href = link.get("href", "")
                if href and not href.startswith("http"):
                    href = urljoin(vc.job_portal_url, href)

                # Get company from nearby text
                parent = link.parent
                company = vc.name
                if parent:
                    company_el = parent.select_one(
                        "span[class*='company'], div[class*='company'], "
                        "span[class*='org'], [class*='employer']"
                    )
                    if company_el:
                        company = company_el.get_text(strip=True) or vc.name

                # Location
                location = ""
                if parent:
                    loc_el = parent.select_one(
                        "span[class*='location'], div[class*='location'], "
                        "span[class*='loc']"
                    )
                    if loc_el:
                        location = loc_el.get_text(strip=True)

                if title and href:
                    jobs.append(Job(
                        platform=f"vc_{vc.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}",
                        title=title,
                        company=company,
                        location=location,
                        salary=None,
                        skills=[],
                        description=f"Via {vc.name} portfolio",
                        apply_link=href,
                    ))
            except Exception:
                self._log.exception("vc.html_item_failed", vc=vc.name)

        return jobs

    async def _get_page(self, url: str, intercept_fn=None) -> Page:
        context = await self.bm.get_context("vc_portals", Path("cookies"))
        page = await context.new_page()
        if intercept_fn:
            page.on("response", intercept_fn)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            self._log.debug("vc.goto_timeout", url=url)
        return page
