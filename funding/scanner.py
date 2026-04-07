from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Page

from browser.context import BrowserManager
from funding.models import FundedCompany

log = structlog.get_logger(__name__)

# Only look at last 6 months
LOOKBACK_DAYS = 180
SERIES_KEYWORDS = [
    "pre-seed",
    "pre-series",
    "series a",
    "series b",
    "series c",
    "series d",
    "series e",
    "series f",
    "seed",
    "bridge",
]


def _extract_amount(text: str) -> str:
    """Extract funding amount like '$15.6M', '₹30 Cr' from text."""
    patterns = [
        r"\$[\d.]+\s*[BMK](?:illion|n)?",
        r"\$[\d.]+\s*(?:million|mn|m)\b",
        r"₹[\d.]+\s*(?:crore|cr|lakh)\b",
        r"\$[\d,.]+",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


def _extract_series(text: str) -> str:
    """Extract round type like 'Series A', 'Seed' from text."""
    for kw in SERIES_KEYWORDS:
        if kw in text.lower():
            # Capitalize properly
            return kw.title()
    return ""


def _parse_date_from_text(text: str) -> date | None:
    """Try multiple date formats."""
    text = text.strip()
    formats = [
        "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%b %Y", "%B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Try extracting month + year
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})", text, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %Y").date()
        except ValueError:
            pass
    return None


class FundingScanner:
    """Scrapes funding news from multiple Indian startup media sources."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.bm = browser_manager
        self._log = log.bind(module="funding_scanner")

    async def scan_all(self) -> list[FundedCompany]:
        """Run all funding source scrapers concurrently."""
        tasks = [
            self._scan_inc42(),
            self._scan_yourstory(),
            self._scan_entrackr(),
            self._scan_vccircle(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_companies: list[FundedCompany] = []
        source_names = ["inc42", "yourstory", "entrackr", "vccircle"]
        for name, result in zip(source_names, results):
            if isinstance(result, Exception):
                self._log.error("source.failed", source=name, error=str(result))
            else:
                self._log.info("source.done", source=name, count=len(result))
                all_companies.extend(result)

        # Deduplicate by company name (case-insensitive), merging fields
        seen: dict[str, FundedCompany] = {}
        for c in all_companies:
            key = c.company.lower().strip()
            if key not in seen:
                seen[key] = c
            else:
                # Field-by-field merge: fill blanks from the new record
                existing = seen[key]
                for field in (
                    "founder_ceo", "founder_linkedin", "industry", "hq_location",
                    "delhi_ncr_office", "amount_raised", "last_round_series",
                    "source_url", "work_mode", "careers_page",
                ):
                    if not getattr(existing, field) and getattr(c, field):
                        setattr(existing, field, getattr(c, field))
                # For date, prefer the more recent one
                if c.last_round_date and (
                    not existing.last_round_date or c.last_round_date > existing.last_round_date
                ):
                    existing.last_round_date = c.last_round_date

        deduped = list(seen.values())
        self._log.info("scan.complete", total=len(all_companies), deduped=len(deduped))
        return deduped

    # ------------------------------------------------------------------
    # Inc42
    # ------------------------------------------------------------------
    async def _scan_inc42(self) -> list[FundedCompany]:
        """Scrape Inc42 funding news."""
        companies: list[FundedCompany] = []
        urls = [
            "https://inc42.com/tag/funding/",
            "https://inc42.com/tag/series-a/",
            "https://inc42.com/tag/series-b/",
        ]
        for url in urls:
            try:
                page = await self._get_page(url)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")

                articles = soup.select("article, div[class*='post-card'], div[class*='article']")
                self._log.info("inc42.articles", count=len(articles), url=url)

                for article in articles[:20]:
                    try:
                        title_el = article.select_one("h2 a, h3 a, a[class*='title']")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        link = title_el.get("href", "")

                        # Filter for funding articles
                        title_lower = title.lower()
                        if not any(kw in title_lower for kw in ["raises", "funding", "secures", "bags", "series", "round"]):
                            continue

                        date_el = article.select_one("time, span[class*='date']")
                        article_date = None
                        if date_el:
                            date_text = date_el.get("datetime", "") or date_el.get_text(strip=True)
                            article_date = _parse_date_from_text(date_text)

                        # Skip if older than 6 months
                        cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                        if article_date and article_date < cutoff:
                            continue

                        # Extract company name from title (usually "X Raises $YM...")
                        company_name = self._extract_company_from_title(title)
                        amount = _extract_amount(title)
                        series = _extract_series(title)

                        if company_name:
                            companies.append(FundedCompany(
                                company=company_name,
                                last_round_date=article_date,
                                last_round_series=series,
                                amount_raised=amount,
                                source_url=link,
                            ))
                    except Exception:
                        self._log.exception("inc42.article_failed")

                await page.close()
            except Exception:
                self._log.exception("inc42.page_failed", url=url)

        return companies

    # ------------------------------------------------------------------
    # YourStory
    # ------------------------------------------------------------------
    async def _scan_yourstory(self) -> list[FundedCompany]:
        """Scrape YourStory funding news."""
        companies: list[FundedCompany] = []
        url = "https://yourstory.com/category/funding"
        try:
            page = await self._get_page(url)
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = soup.select(
                "article, div[class*='story-card'], div[class*='post'], "
                "a[class*='story']"
            )
            self._log.info("yourstory.articles", count=len(articles))

            for article in articles[:30]:
                try:
                    title_el = article.select_one("h2, h3, span[class*='title']")
                    if not title_el:
                        link_el = article if article.name == "a" else article.select_one("a")
                        title = link_el.get_text(strip=True) if link_el else ""
                    else:
                        title = title_el.get_text(strip=True)

                    link_el = article.select_one("a[href]") or (article if article.name == "a" else None)
                    link = link_el.get("href", "") if link_el else ""
                    if link and not link.startswith("http"):
                        link = f"https://yourstory.com{link}"

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in ["raises", "funding", "secures", "bags", "series", "round", "investment"]):
                        continue

                    date_el = article.select_one("time, span[class*='date']")
                    article_date = _parse_date_from_text(
                        date_el.get("datetime", "") or date_el.get_text(strip=True)
                    ) if date_el else None

                    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                    if article_date and article_date < cutoff:
                        continue

                    company_name = self._extract_company_from_title(title)
                    amount = _extract_amount(title)
                    series = _extract_series(title)

                    if company_name:
                        companies.append(FundedCompany(
                            company=company_name,
                            last_round_date=article_date,
                            last_round_series=series,
                            amount_raised=amount,
                            source_url=link,
                        ))
                except Exception:
                    self._log.exception("yourstory.article_failed")

            await page.close()
        except Exception:
            self._log.exception("yourstory.page_failed")

        return companies

    # ------------------------------------------------------------------
    # Entrackr
    # ------------------------------------------------------------------
    async def _scan_entrackr(self) -> list[FundedCompany]:
        """Scrape Entrackr funding news."""
        companies: list[FundedCompany] = []
        url = "https://entrackr.com/category/funding/"
        try:
            page = await self._get_page(url)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = soup.select("article, div[class*='post'], div[class*='entry']")
            self._log.info("entrackr.articles", count=len(articles))

            for article in articles[:20]:
                try:
                    title_el = article.select_one("h2 a, h3 a, a[class*='title']")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in ["raises", "funding", "secures", "bags", "series"]):
                        continue

                    date_el = article.select_one("time, span[class*='date']")
                    article_date = _parse_date_from_text(
                        date_el.get("datetime", "") or date_el.get_text(strip=True)
                    ) if date_el else None

                    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                    if article_date and article_date < cutoff:
                        continue

                    company_name = self._extract_company_from_title(title)
                    amount = _extract_amount(title)
                    series = _extract_series(title)

                    if company_name:
                        companies.append(FundedCompany(
                            company=company_name,
                            last_round_date=article_date,
                            last_round_series=series,
                            amount_raised=amount,
                            source_url=link,
                        ))
                except Exception:
                    self._log.exception("entrackr.article_failed")

            await page.close()
        except Exception:
            self._log.exception("entrackr.page_failed")

        return companies

    # ------------------------------------------------------------------
    # VCCircle
    # ------------------------------------------------------------------
    async def _scan_vccircle(self) -> list[FundedCompany]:
        """Scrape VCCircle funding news."""
        companies: list[FundedCompany] = []
        url = "https://www.vccircle.com/deals"
        try:
            page = await self._get_page(url)
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = soup.select(
                "article, div[class*='deal-card'], div[class*='story'], "
                "div[class*='post'], li[class*='deal']"
            )
            self._log.info("vccircle.articles", count=len(articles))

            for article in articles[:20]:
                try:
                    title_el = article.select_one("h2 a, h3 a, a[class*='title'], a[class*='headline']")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")
                    if link and not link.startswith("http"):
                        link = f"https://www.vccircle.com{link}"

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in ["raises", "funding", "secures", "bags", "series", "round"]):
                        continue

                    date_el = article.select_one("time, span[class*='date']")
                    article_date = _parse_date_from_text(
                        date_el.get("datetime", "") or date_el.get_text(strip=True)
                    ) if date_el else None

                    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                    if article_date and article_date < cutoff:
                        continue

                    company_name = self._extract_company_from_title(title)
                    amount = _extract_amount(title)
                    series = _extract_series(title)

                    if company_name:
                        companies.append(FundedCompany(
                            company=company_name,
                            last_round_date=article_date,
                            last_round_series=series,
                            amount_raised=amount,
                            source_url=link,
                        ))
                except Exception:
                    self._log.exception("vccircle.article_failed")

            await page.close()
        except Exception:
            self._log.exception("vccircle.page_failed")

        return companies

    # ------------------------------------------------------------------
    # LinkedIn cross-reference
    # ------------------------------------------------------------------
    async def check_linkedin_pm_roles(self, companies: list[FundedCompany]) -> None:
        """For each funded company, check LinkedIn for open PM roles."""
        for company in companies:
            try:
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords=product+manager&company={company.company.replace(' ', '+')}"
                    f"&location=India"
                )
                company.linkedin_jobs_url = search_url

                page = await self._get_page(search_url)
                await asyncio.sleep(2)

                # Check if blocked
                if "authwall" in page.url or "login" in page.url:
                    self._log.debug("linkedin.auth_wall", company=company.company)
                    await page.close()
                    continue

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Count job cards, validating company name and PM role
                cards = soup.select("div.base-card, li.result-card")
                company_lower = company.company.lower()
                pm_keywords = {"product manager", "product management", "senior pm", "head of product"}
                validated = 0
                for card in cards:
                    card_text = card.get_text(" ", strip=True).lower()
                    # Check both company name and PM keyword appear
                    if any(kw in card_text for kw in pm_keywords):
                        # Company name check: at least partial match
                        company_words = company_lower.split()
                        if any(w in card_text for w in company_words if len(w) > 2):
                            validated += 1
                company.linkedin_pm_roles = validated

                self._log.info(
                    "linkedin.checked",
                    company=company.company,
                    pm_roles=company.linkedin_pm_roles,
                )
                await page.close()
                await asyncio.sleep(3)  # Rate limit
            except Exception:
                self._log.debug("linkedin.check_failed", company=company.company)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _get_page(self, url: str) -> Page:
        from pathlib import Path
        context = await self.bm.get_context("funding_scanner", Path("cookies"))
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            try:
                await page.close()
            except Exception:
                pass
            raise
        return page

    @staticmethod
    def _extract_company_from_title(title: str) -> str:
        """Extract company name from funding headline.

        Patterns: "CompanyX Raises $10M...", "CompanyX Bags Series A...",
        "CompanyX Secures Funding..."
        """
        # Try pattern: "Company Raises/Bags/Secures/Gets..."
        patterns = [
            r"^(.+?)\s+(?:raises?|bags?|secures?|gets?|closes?|lands?|nabs?)\s",
            r"^(.+?)\s+(?:funding|series|round)\b",
        ]
        for pat in patterns:
            m = re.match(pat, title, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Clean up prefixes
                for prefix in ["Startup", "Company", "Indian"]:
                    if name.startswith(prefix + " "):
                        name = name[len(prefix) + 1:]
                # Remove quotes
                name = name.strip("'\"")
                if len(name) > 2 and not any(c in name.lower() for c in ["funding", "series", "raises"]):
                    return name

        return ""
