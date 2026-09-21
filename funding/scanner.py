from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
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
    # Inc42  (RSS — no Playwright needed; Gatsby SPA returns empty shell)
    # ------------------------------------------------------------------
    async def _scan_inc42(self) -> list[FundedCompany]:
        """Fetch Inc42 funding news via RSS feed (more reliable than Playwright on SPA)."""
        companies: list[FundedCompany] = []
        rss_url = "https://inc42.com/feed/"
        funding_kws = ["raises", "funding", "secures", "bags", "series", "round",
                       "crore", "million", "investment", "backed", "nabs", "lands",
                       "closes", "gets", "receives"]
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
                timeout=15,
            ) as client:
                resp = await client.get(rss_url)
                resp.raise_for_status()

            root = ET.fromstring(resp.text)
            items = root.findall(".//item")
            self._log.info("inc42.rss_items", count=len(items))

            cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
            for item in items:
                try:
                    title = item.findtext("title", "").strip()
                    link = item.findtext("link", "").strip()
                    pub_date_str = item.findtext("pubDate", "")

                    article_date: date | None = None
                    if pub_date_str:
                        try:
                            article_date = parsedate_to_datetime(pub_date_str).date()
                        except Exception:
                            article_date = _parse_date_from_text(pub_date_str)

                    if article_date and article_date < cutoff:
                        continue

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in funding_kws):
                        continue

                    company_name = self._extract_company_from_title(title)
                    if not company_name:
                        continue

                    companies.append(FundedCompany(
                        company=company_name,
                        last_round_date=article_date,
                        last_round_series=_extract_series(title),
                        amount_raised=_extract_amount(title),
                        source_url=link,
                    ))
                except Exception:
                    self._log.exception("inc42.item_failed")

        except Exception:
            self._log.exception("inc42.rss_failed", url=rss_url)

        return companies

    # ------------------------------------------------------------------
    # YourStory
    # ------------------------------------------------------------------
    async def _scan_yourstory(self) -> list[FundedCompany]:
        """Scrape YourStory funding news."""
        companies: list[FundedCompany] = []
        url = "https://yourstory.com/category/funding"
        funding_kws = ["raises", "funding", "secures", "bags", "series", "round", "investment", "crore", "million"]
        try:
            page = await self._get_page(url)
            # Wait longer for React/Next.js SPA to render article cards
            try:
                await page.wait_for_selector("article, [class*='story'], [class*='article-card'], h2 a, h3 a", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Try multiple selector strategies
            articles = (
                soup.select("article")
                or soup.select("[class*='story-card']")
                or soup.select("[class*='article-card']")
                or soup.select("[class*='post-card']")
                or soup.select("a[href*='/funding/']")
            )
            self._log.info("yourstory.articles", count=len(articles))

            for article in articles[:30]:
                try:
                    title_el = article.select_one("h2, h3, h4, [class*='title']")
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
                    if not title or not any(kw in title_lower for kw in funding_kws):
                        continue

                    date_el = article.select_one("time, [class*='date'], [class*='time']")
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
    # Entrackr  (Playwright — SPA with wait for JS render)
    # ------------------------------------------------------------------
    async def _scan_entrackr(self) -> list[FundedCompany]:
        """Scrape Entrackr funding news."""
        companies: list[FundedCompany] = []
        url = "https://entrackr.com/category/funding/"
        funding_kws = ["raises", "funding", "secures", "bags", "series", "round", "crore", "million"]
        try:
            page = await self._get_page(url)
            try:
                await page.wait_for_selector("article, h2 a, h3 a, [class*='post-title']", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = (
                soup.select("article")
                or soup.select("[class*='post-item']")
                or soup.select("[class*='story-card']")
                or soup.select("h2 a, h3 a")
            )
            self._log.info("entrackr.articles", count=len(articles))

            for article in articles[:20]:
                try:
                    # For bare anchor elements, the element IS the link+title
                    if article.name == "a":
                        title = article.get_text(strip=True)
                        link = article.get("href", "")
                    else:
                        title_el = article.select_one("h2 a, h3 a, h2, h3, [class*='title']")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        link_el = title_el if title_el.name == "a" else title_el.select_one("a[href]")
                        link = link_el.get("href", "") if link_el else ""

                    title_lower = title.lower()
                    if not title or not any(kw in title_lower for kw in funding_kws):
                        continue

                    date_el = article.select_one("time, [class*='date'], [class*='time']")
                    article_date = _parse_date_from_text(
                        date_el.get("datetime", "") or date_el.get_text(strip=True)
                    ) if date_el else None

                    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                    if article_date and article_date < cutoff:
                        continue

                    company_name = self._extract_company_from_title(title)
                    if not company_name:
                        continue

                    companies.append(FundedCompany(
                        company=company_name,
                        last_round_date=article_date,
                        last_round_series=_extract_series(title),
                        amount_raised=_extract_amount(title),
                        source_url=link,
                    ))
                except Exception:
                    self._log.exception("entrackr.article_failed")

            await page.close()
        except Exception:
            self._log.exception("entrackr.page_failed")

        return companies

    # ------------------------------------------------------------------
    # VCCircle  (Playwright — SPA with wait for JS render)
    # ------------------------------------------------------------------
    async def _scan_vccircle(self) -> list[FundedCompany]:
        """Scrape VCCircle funding news."""
        companies: list[FundedCompany] = []
        url = "https://www.vccircle.com/deals"
        funding_kws = ["raises", "funding", "secures", "bags", "series", "round", "investment", "acqui"]
        try:
            page = await self._get_page(url)
            try:
                await page.wait_for_selector("article, h2 a, h3 a, [class*='deal'], [class*='headline']", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = (
                soup.select("article")
                or soup.select("[class*='deal-card']")
                or soup.select("[class*='story-item']")
                or soup.select("[class*='post-item']")
                or soup.select("h2 a, h3 a")
            )
            self._log.info("vccircle.articles", count=len(articles))

            for article in articles[:20]:
                try:
                    if article.name == "a":
                        title = article.get_text(strip=True)
                        link = article.get("href", "")
                        if link and not link.startswith("http"):
                            link = f"https://www.vccircle.com{link}"
                    else:
                        title_el = article.select_one("h2 a, h3 a, h2, h3, [class*='title'], [class*='headline']")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        link_el = title_el if title_el.name == "a" else title_el.select_one("a[href]")
                        link = link_el.get("href", "") if link_el else ""
                        if link and not link.startswith("http"):
                            link = f"https://www.vccircle.com{link}"

                    title_lower = title.lower()
                    if not title or not any(kw in title_lower for kw in funding_kws):
                        continue

                    date_el = article.select_one("time, [class*='date'], [class*='time']")
                    article_date = _parse_date_from_text(
                        date_el.get("datetime", "") or date_el.get_text(strip=True)
                    ) if date_el else None

                    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
                    if article_date and article_date < cutoff:
                        continue

                    company_name = self._extract_company_from_title(title)
                    if not company_name:
                        continue

                    companies.append(FundedCompany(
                        company=company_name,
                        last_round_date=article_date,
                        last_round_series=_extract_series(title),
                        amount_raised=_extract_amount(title),
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
        from config.settings import Settings

        context = await self.bm.get_context("funding_scanner", Settings().COOKIES_DIR)
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
