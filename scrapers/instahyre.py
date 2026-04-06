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
    if "just" in text or "today" in text:
        return today
    if "yesterday" in text:
        return today - timedelta(days=1)
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


class InstahyreScraper(BaseScraper):
    """Instahyre scraper — fully login-gated."""

    name: str = "instahyre"
    requires_login: bool = True

    async def scrape(self) -> list[Job]:
        page = await self._get_page("https://www.instahyre.com/search-jobs/")

        # Detect session expiry
        if "login" in page.url.lower():
            self._log.warning("session.expired", redirect_url=page.url)
            await page.close()
            return []

        # Wait for job cards to render
        try:
            await page.wait_for_selector(
                "div[class*='job'], div[class*='opportunity'], "
                "div[class*='card']",
                timeout=12_000,
            )
        except Exception:
            self._log.debug("wait.timeout")

        await asyncio.sleep(2)

        all_jobs: list[Job] = []

        # Scroll to load more results
        prev_count = 0
        for _ in range(5):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            cards = (
                soup.select("div[class*='opportunity-card']")
                or soup.select("div[class*='job-card']")
                or soup.select("div[class*='card'][class*='job']")
                or soup.select("div.card")
            )
            if len(cards) == prev_count:
                break
            prev_count = len(cards)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        cards = (
            soup.select("div[class*='opportunity-card']")
            or soup.select("div[class*='job-card']")
            or soup.select("div[class*='card'][class*='job']")
            or soup.select("div.card")
        )

        self._log.info("html.cards_found", count=len(cards))

        for card in cards:
            try:
                title_el = card.select_one(
                    "h3, h2, div[class*='title'], span[class*='title'], "
                    "a[class*='title']"
                )
                title = title_el.get_text(strip=True) if title_el else ""

                link_el = card.select_one("a[href]")
                href = link_el.get("href", "") if link_el else ""
                apply_link = (
                    f"https://www.instahyre.com{href}"
                    if href and not href.startswith("http")
                    else href
                )

                company_el = card.select_one(
                    "span[class*='company'], div[class*='company'], "
                    "p[class*='company'], h4"
                )
                company = company_el.get_text(strip=True) if company_el else ""

                loc_el = card.select_one(
                    "span[class*='loc'], div[class*='location'], "
                    "span[class*='location']"
                )
                location = loc_el.get_text(strip=True) if loc_el else ""

                salary_el = card.select_one(
                    "span[class*='salary'], span[class*='ctc'], "
                    "div[class*='salary']"
                )
                salary = salary_el.get_text(strip=True) if salary_el else None

                skills_els = card.select(
                    "span[class*='skill'], span[class*='tag'], "
                    "div[class*='skill'] span"
                )
                skills = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]

                date_el = card.select_one("span[class*='date'], time")
                posted_date = _parse_relative_date(
                    date_el.get_text(strip=True) if date_el else ""
                )

                if not (title and apply_link):
                    continue

                all_jobs.append(
                    Job(
                        platform="instahyre",
                        title=title,
                        company=company,
                        location=location,
                        salary=salary,
                        posted_date=posted_date,
                        skills=skills,
                        description="",
                        apply_link=apply_link,
                    )
                )
            except Exception:
                self._log.exception("card.parse_failed")

        await page.close()
        return all_jobs
