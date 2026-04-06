from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "today" in text or "just" in text:
        return today
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", text)
    if m:
        return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*month", text)
    if m:
        return today - timedelta(days=int(m.group(1)) * 30)
    return None


class YCombinatorScraper(BaseScraper):
    """Scrape YC Work at a Startup for PM roles.

    Uses the public-facing job listing pages rather than the login-gated search.
    """

    name: str = "ycombinator"
    requires_login: bool = False

    async def scrape(self) -> list[Job]:
        # YC has public job listing pages
        urls = [
            "https://www.ycombinator.com/jobs/role/product-manager",
            "https://www.workatastartup.com/jobs?role=product_manager&location=India",
        ]

        all_jobs: list[Job] = []

        for url in urls:
            try:
                self._log.info("page.scraping", url=url)
                page = await self._get_page(url)

                # Wait for React to render
                try:
                    await page.wait_for_selector(
                        "div[class*='job'], a[class*='job'], div[class*='company'], "
                        "div[class*='listing']",
                        timeout=12_000,
                    )
                except Exception:
                    self._log.debug("wait.timeout", url=url)

                await asyncio.sleep(3)

                # Scroll to load more
                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.5)

                html = await page.content()
                jobs = self._parse_page(html, url)
                all_jobs.extend(jobs)
                self._log.info("page.collected", url=url, jobs=len(jobs))

                await page.close()
                await asyncio.sleep(2)
            except Exception:
                self._log.exception("page.failed", url=url)

        return all_jobs

    def _parse_page(self, html: str, source_url: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []

        # Try multiple selectors for different page layouts
        cards = (
            soup.select("div[class*='JobListing']")
            or soup.select("a[class*='job-listing']")
            or soup.select("div[class*='job-card']")
            or soup.select("div[class*='company-job']")
            or soup.select("tr[class*='job']")
            or soup.select("div[class*='listing']")
        )

        self._log.info("html.cards_found", count=len(cards))

        pm_keywords = {"product manager", "product management", "senior pm",
                        "head of product", "director product"}

        for card in cards:
            try:
                text = card.get_text(" ", strip=True).lower()
                # Only include PM roles
                if not any(kw in text for kw in pm_keywords):
                    continue

                title_el = card.select_one("h2, h3, h4, span[class*='title'], div[class*='title']")
                title = title_el.get_text(strip=True) if title_el else ""

                link_el = card.select_one("a[href]") or (card if card.name == "a" else None)
                href = link_el.get("href", "") if link_el else ""
                if href and not href.startswith("http"):
                    if "workatastartup" in source_url:
                        href = f"https://www.workatastartup.com{href}"
                    else:
                        href = f"https://www.ycombinator.com{href}"

                company_el = card.select_one(
                    "span[class*='company'], div[class*='company'], h4, "
                    "a[class*='company']"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one("span[class*='location'], div[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one("span[class*='salary'], div[class*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None

                if not (title and href):
                    continue

                jobs.append(
                    Job(
                        platform="ycombinator",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        skills=[],
                        description="YC-backed startup",
                        apply_link=href,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        return jobs
