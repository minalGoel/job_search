from __future__ import annotations

import asyncio
import random
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper

log = structlog.get_logger(__name__)

MAX_PAGES = 3
MAX_DETAIL_FETCHES = 10


def _parse_relative_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip().lower()
    today = date.today()
    if "just" in text or "now" in text or "today" in text:
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
    m = re.search(r"(\d+)\s*hour", text)
    if m:
        return today
    return None


class LinkedInScraper(BaseScraper):
    """LinkedIn scraper using guest search. Extra cautious to avoid blocks."""

    name: str = "linkedin"
    requires_login: bool = False

    def _build_search_url(self, page_num: int = 1) -> str:
        sp = self.search_params
        keyword = "+".join(sp.title_keywords[0].split())
        base = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={keyword}"
            f"&location=Delhi+NCR"
            f"&f_E=4"        # senior level
            f"&f_TPR=r604800"  # past week
        )
        if page_num > 1:
            base += f"&start={(page_num - 1) * 25}"
        return base

    async def scrape(self) -> list[Job]:
        all_jobs: list[Job] = []
        detail_fetches = 0

        for page_num in range(1, MAX_PAGES + 1):
            url = self._build_search_url(page_num)
            self._log.info("page.scraping", page=page_num, url=url)

            # Extra delay for LinkedIn
            await asyncio.sleep(random.uniform(3.0, 7.0))

            try:
                page = await self._get_page(url)
            except Exception:
                self._log.warning("page.blocked_or_failed", page=page_num)
                break

            # Check for auth wall
            current_url = page.url
            if "authwall" in current_url or "login" in current_url:
                self._log.warning("page.auth_wall", url=current_url)
                await page.close()
                break

            # Scroll down to load lazy content
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            cards = (
                soup.select("div.base-card")
                or soup.select("li.result-card")
                or soup.select("div[class*='job-search-card']")
                or soup.select("ul.jobs-search__results-list > li")
            )

            self._log.info("html.cards_found", count=len(cards), page=page_num)
            if not cards:
                await page.close()
                break

            for card in cards:
                try:
                    title_el = card.select_one(
                        "h3.base-search-card__title, h3[class*='title'], "
                        "span[class*='sr-only']"
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    link_el = card.select_one("a.base-card__full-link, a[class*='card']")
                    apply_link = link_el.get("href", "").split("?")[0] if link_el else ""

                    company_el = card.select_one(
                        "h4.base-search-card__subtitle, a[class*='subtitle']"
                    )
                    company = company_el.get_text(strip=True) if company_el else ""

                    loc_el = card.select_one("span.job-search-card__location, span[class*='location']")
                    location = loc_el.get_text(strip=True) if loc_el else ""

                    date_el = card.select_one("time, span[class*='date']")
                    date_text = date_el.get("datetime", "") or (date_el.get_text(strip=True) if date_el else "")
                    posted_date = _parse_relative_date(date_text)

                    if not (title and apply_link):
                        continue

                    # Fetch description for a limited number of jobs
                    description = ""
                    if detail_fetches < MAX_DETAIL_FETCHES and apply_link:
                        description = await self._fetch_description(apply_link)
                        detail_fetches += 1

                    all_jobs.append(
                        Job(
                            platform="linkedin",
                            title=title,
                            company=company,
                            location=location,
                            posted_date=posted_date,
                            skills=[],
                            description=description,
                            apply_link=apply_link,
                        )
                    )
                except Exception:
                    self._log.exception("card.parse_failed")

            await page.close()
            self._log.info("page.collected", page=page_num, jobs=len(all_jobs))

        return all_jobs

    async def _fetch_description(self, url: str) -> str:
        if not url:
            return ""
        try:
            await asyncio.sleep(random.uniform(3.0, 6.0))
            page = await self._get_page(url)

            # Check for auth wall
            if "authwall" in page.url or "login" in page.url:
                await page.close()
                return ""

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div.show-more-less-html__markup, div[class*='description__text'], "
                "section[class*='description'] div"
            )
            description = jd_el.get_text(separator="\n", strip=True) if jd_el else ""
            await page.close()
            return description
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
