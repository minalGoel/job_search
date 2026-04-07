from __future__ import annotations

import asyncio
import random
import re
from datetime import date, timedelta

import structlog
from bs4 import BeautifulSoup

from models.job import Job
from scrapers.base import BaseScraper
from services.location_filter import is_acceptable_location, explain as explain_location

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
            f"&location=Delhi%2C+India"
            f"&f_TPR=r2592000"  # past 30 days (broader window for more results)
            # f_E filter removed — "Senior" filter was returning only 2 results
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

            page = None
            try:
                try:
                    page = await self._get_page(url)
                except Exception:
                    self._log.warning("page.blocked_or_failed", page=page_num)
                    break

                # Check for auth wall
                current_url = page.url
                if "authwall" in current_url or "login" in current_url:
                    self._log.warning("page.auth_wall", url=current_url)
                    break

                # Scroll down to load lazy content
                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.5)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Logged-in selectors (confirmed April 2026): div.job-card-container
                cards = (
                    soup.select("div.job-card-container")
                    or soup.select("div.base-card")
                    or soup.select("li.result-card")
                    or soup.select("div[class*='job-search-card']")
                    or soup.select("ul.jobs-search__results-list > li")
                )

                self._log.info("html.cards_found", count=len(cards), page=page_num)
                if not cards:
                    break
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass

            for card in cards:
                try:
                    # Logged-in selectors
                    title_el = card.select_one(
                        "a.job-card-container__link, .job-card-list__title, "
                        "h3.base-search-card__title, h3[class*='title']"
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    link_el = card.select_one(
                        "a.job-card-container__link, a.base-card__full-link, a[href*='/jobs/view/']"
                    )
                    apply_link = link_el.get("href", "").split("?")[0] if link_el else ""

                    company_el = card.select_one(
                        ".job-card-container__primary-description, "
                        "h4.base-search-card__subtitle, a[class*='subtitle']"
                    )
                    company = company_el.get_text(strip=True) if company_el else ""

                    loc_el = card.select_one(
                        ".job-card-container__metadata-item, "
                        "span.job-search-card__location, span[class*='location']"
                    )
                    location = loc_el.get_text(strip=True) if loc_el else ""

                    date_el = card.select_one("time, span[class*='date'], span[class*='listdate']")
                    date_text = date_el.get("datetime", "") or (date_el.get_text(strip=True) if date_el else "")
                    posted_date = _parse_relative_date(date_text)

                    if not (title and apply_link):
                        continue

                    if not is_acceptable_location(location):
                        self._log.debug(
                            "linkedin.filtered_location",
                            title=title, company=company,
                            reason=explain_location(location),
                        )
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

            self._log.info("page.collected", page=page_num, jobs=len(all_jobs))

        return all_jobs

    async def _fetch_description(self, url: str) -> str:
        if not url:
            return ""
        page = None
        try:
            await asyncio.sleep(random.uniform(3.0, 6.0))
            page = await self._get_page(url)

            # Check for auth wall
            if "authwall" in page.url or "login" in page.url:
                return ""

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            jd_el = soup.select_one(
                "div.show-more-less-html__markup, div[class*='description__text'], "
                "section[class*='description'] div"
            )
            return jd_el.get_text(separator="\n", strip=True) if jd_el else ""
        except Exception:
            self._log.debug("description.fetch_failed", url=url)
            return ""
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
