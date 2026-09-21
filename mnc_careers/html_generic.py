"""Playwright HTML lane for career sites without a typed ATS fetcher.

Returns raw postings only (no Job construction, no filtering — see
``mnc_careers/filter.py``). Three strategies, merged by URL:

1. **JSON interception** — any JSON response the page loads whose body
   contains a list of job-like dicts (title-ish *and* url/id-ish keys) is
   parsed. This catches Eightfold (``positions``), Phenom
   (``refineSearch.data.jobs``), Radancy and most SPA back-ends *with the
   browser's session* — which is why Eightfold lives here, not in a typed
   fetcher.
2. **Card selectors** on the rendered DOM (the historical selector chains,
   kept verbatim).
3. **Pagination** — "Next" / "Load more" up to ``max_pages``, stopping when
   no new hrefs appear.

If the registry URL carried a ``?q=`` search, the stripped *listing* URL is
the primary page and the original search URL is loaded once more as a
supplementary net (guidelines §12: portal search is a hint, not a filter).
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Page, Response

from browser.context import BrowserManager
from mnc_careers.ats.base import FetchResult, RawPosting

_TITLE_KEYS = ("title", "name", "jobTitle", "job_title", "text", "positionTitle")
_URL_KEYS = (
    "url", "applyUrl", "apply_url", "jobUrl", "job_url", "hostedUrl", "absolute_url", "absoluteUrl",
    "canonicalPositionUrl", "externalPath", "jobSeqNo", "id", "jobId", "job_id", "reqId", "slug", "detailUrl",
)
_LOC_KEYS = ("location", "locations", "locationsText", "jobLocation", "city", "cityState", "cityStateCountry", "primaryLocation", "normalized_location")

_NEXT_SELECTORS = [
    "a[rel='next']",
    "a[aria-label*='Next' i]",
    "button[aria-label*='Next' i]",
    "a:has-text('Next')",
    "button:has-text('Next')",
    "button:has-text('Load more')",
    "button:has-text('Show more')",
    "button:has-text('View more')",
    "a:has-text('Load more')",
    "a:has-text('Show more')",
]

# Consent banners block the page's own JS on many career sites (SuccessFactors
# "Unify" sites don't even fire their search until cookies are accepted).
_CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#truste-consent-button",
    "button[id*='accept' i]",
    "button[class*='accept' i]",
    "a[id*='accept' i]",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Agree')",
    "button:has-text('Allow all')",
    "button:has-text('OK')",
]

WAIT_SELECTOR = (
    "div[class*='job'], a[class*='job'], li[class*='job'], "
    "div[class*='position'], div[class*='result'], tr[class*='job']"
)


# ----------------------------------------------------------------------------
# JSON interception
# ----------------------------------------------------------------------------

def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _is_joblike(item: Any) -> bool:
    return isinstance(item, dict) and _first(item, _TITLE_KEYS) is not None and _first(item, _URL_KEYS) is not None


def find_job_lists(node: Any, depth: int = 0) -> list[list[dict[str, Any]]]:
    """Recursively find lists whose items look like job postings."""
    found: list[list[dict[str, Any]]] = []
    if depth > 6:
        return found
    if isinstance(node, list):
        joblike = [x for x in node if _is_joblike(x)]
        if joblike and len(joblike) >= max(1, len(node) // 2):
            found.append(joblike)
            return found
        for x in node:
            found.extend(find_job_lists(x, depth + 1))
    elif isinstance(node, dict):
        for v in node.values():
            found.extend(find_job_lists(v, depth + 1))
    return found


def _location_of(item: dict[str, Any]) -> str:
    v = _first(item, _LOC_KEYS)
    if v is None:
        return ""
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(", ".join(str(x.get(k)) for k in ("city", "state", "country", "name") if x.get(k)))
            else:
                parts.append(str(x))
        return "; ".join(p for p in parts if p)
    if isinstance(v, dict):
        return ", ".join(str(v.get(k)) for k in ("city", "state", "region", "country", "name") if v.get(k))
    return str(v)


def postings_from_json(body: Any, base_url: str) -> list[RawPosting]:
    out: list[RawPosting] = []
    for lst in find_job_lists(body):
        for it in lst:
            title = str(_first(it, _TITLE_KEYS) or "").strip()
            raw_url = _first(it, _URL_KEYS)
            url = str(raw_url or "").strip()
            if url and not url.startswith("http"):
                url = urljoin(base_url, url if url.startswith("/") else f"/{url}")
            if not (title and url):
                continue
            out.append(RawPosting(title=title, location=_location_of(it), url=url,
                                  posted_on=str(_first(it, ("postedOn", "postedDate", "posted_date", "createdAt", "t_create", "releasedDate")) or "")))
    return out


# ----------------------------------------------------------------------------
# DOM parsing (historical selector chains, unchanged)
# ----------------------------------------------------------------------------

def parse_cards(html: str, base_url: str) -> list[RawPosting]:
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
    listings = [el for el in listings if el.get_text(strip=True)]
    out: list[RawPosting] = []
    for el in listings:
        try:
            title_el = (
                el.select_one("h2, h3, h4")
                or el.select_one("a[class*='title'], span[class*='title'], div[class*='title']")
                or el.select_one("[class*='job-title'], [class*='jobtitle'], [class*='role-title'], [class*='position-title']")
                or el.select_one("a[href]")
            )
            title = title_el.get_text(strip=True) if title_el else ""
            link_el = el.select_one("a[href]") or (el if el.name == "a" else None)
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = urljoin(base_url, href)
            # Location — most-specific to least-specific. Never default to the
            # registry's delhi_ncr_office: an unresolvable location is rejected downstream.
            loc_el = (
                el.select_one("h2[class*='location'], h3[class*='location'], h4[class*='location']")
                or el.select_one("span[class*='location'], div[class*='location'], span[class*='loc']")
                or el.select_one("li[class*='location'], p[class*='location']")
                or el.select_one("[data-testid*='location'], [data-automation*='location']")
                or el.select_one("[class*='job-location'], [class*='jobLocation']")
                or el.select_one("[class*='city'], [class*='region'], [class*='country']")
                or el.select_one("span[class*='meta'], div[class*='meta']")
            )
            location = loc_el.get_text(strip=True) if loc_el else ""
            if title and href:
                out.append(RawPosting(title=title, location=location, url=href))
        except Exception:
            continue
    return out


_JOBISH_URL_RE = re.compile(r"/(job|jobs|career|careers|position|positions|vacanc|opening|posting|requisition|req|jd|search-results|details)[/\-_?]|[/_-]\d{4,}(?:[/?#]|$)|[?&](job|jobid|req|id|posting)=", re.I)


def looks_like_job_url(url: str) -> bool:
    """Heuristic used by discovery: does this href point at a job posting/listing?"""
    return bool(_JOBISH_URL_RE.search(url or ""))


# ----------------------------------------------------------------------------
# Lane entry point
# ----------------------------------------------------------------------------

async def _open(bm: BrowserManager, url: str, cookies_dir: Path, intercept) -> Page:  # noqa: ANN001
    context = await bm.get_context("mnc_careers", cookies_dir)
    page = await context.new_page()
    page.on("response", intercept)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        try:
            await page.close()
        except Exception:
            pass
        raise
    return page


async def _dismiss_consent(page: Page) -> bool:
    for sel in _CONSENT_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click(timeout=3_000)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _collect(page: Page, url: str, captured: list[RawPosting], *, max_pages: int, log: Any, company: str) -> tuple[list[RawPosting], int, int]:
    postings: list[RawPosting] = []
    seen: set[str] = set()
    pages = 0
    await asyncio.sleep(2)
    if await _dismiss_consent(page):
        log.debug("mnc.consent_dismissed", company=company)
        await asyncio.sleep(3)
    else:
        await asyncio.sleep(1)
    try:
        await page.wait_for_selector(WAIT_SELECTOR, timeout=12_000)
    except Exception:
        log.debug("mnc.wait_timeout", company=company)

    json_count = 0
    for _ in range(max_pages):
        pages += 1
        html = await page.content()
        new = 0
        for p in captured:
            if p.url not in seen:
                seen.add(p.url)
                postings.append(p)
                new += 1
                json_count += 1
        for p in parse_cards(html, url):
            if p.url not in seen:
                seen.add(p.url)
                postings.append(p)
                new += 1
        captured.clear()
        if new == 0 and pages > 1:
            break
        clicked = False
        for sel in _NEXT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    await el.click(timeout=5_000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break
        await asyncio.sleep(3)
    return postings, pages, json_count


async def fetch_all(
    mnc: Any,
    bm: BrowserManager,
    *,
    cookies_dir: Path,
    max_pages: int,
    listing_url: str,
    net_url: str,
    log: Any,
) -> FetchResult:
    captured: list[RawPosting] = []

    async def _intercept(response: Response) -> None:
        try:
            if response.status != 200 or "json" not in response.headers.get("content-type", ""):
                return
            body = await response.json()
            captured.extend(postings_from_json(body, listing_url))
        except Exception:
            pass

    result = FetchResult(strategy="html")
    all_postings: list[RawPosting] = []
    seen: set[str] = set()
    for label, url in (("listing", listing_url), ("net", net_url)):
        if not url or (label == "net" and url == listing_url):
            continue
        page: Optional[Page] = None
        try:
            page = await _open(bm, url, cookies_dir, _intercept)
            postings, pages, json_count = await _collect(page, url, captured, max_pages=max_pages, log=log, company=mnc.name)
            result.pages += pages
            result.json_postings += json_count
            added = 0
            for p in postings:
                if p.url not in seen:
                    seen.add(p.url)
                    all_postings.append(p)
                    added += 1
            result.strategy += f"+{label}({added})"
        except Exception as exc:
            if label == "listing":
                raise
            log.debug("mnc.net_page_failed", company=mnc.name, url=url, error=str(exc))
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
    result.postings = all_postings
    result.total_reported = None
    return result
