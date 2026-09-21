"""Avature career sites (``…/SearchJobs``, e.g. bloomberg.avature.net, careers.hyatt.com).

Server-rendered listing: ``GET {base}/SearchJobs/?jobOffset=N`` (12 per page)
with ``article.article--result`` → ``h3 a`` (title + href) and
``span.list-item-location``. The total appears as "N results/jobs" in the page.
Keyword net: ``{base}/SearchJobs/{keyword}?jobOffset=N``.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from mnc_careers.ats.base import FetchError, FetchResult, NotThisATS, RawPosting, TitlePredicate, looks_like_challenge, merge, paginate, request

_TOTAL_RE = re.compile(r"(\d[\d,]*)\s+(?:results?|jobs?|positions?|opportunit)", re.I)


def parse_base(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    i = path.lower().find("/searchjobs")
    base_path = path[:i] if i >= 0 else path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{base_path}"


def parse_listing(html: str, base_url: str) -> tuple[list[RawPosting], Optional[int]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawPosting] = []
    for art in soup.select("article.article--result, li.article--result, div.article--result"):
        a = art.select_one("h3 a, h2 a, .article__header__text__title a, a[href*='JobDetail']")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = urljoin(base_url, a.get("href", ""))
        loc_el = art.select_one(".list-item-location, .article__header__text__subtitle, [class*='location']")
        location = loc_el.get_text(" ", strip=True) if loc_el else ""
        if title and href:
            out.append(RawPosting(title=title, location=location, url=href))
    total: Optional[int] = None
    m = _TOTAL_RE.search(soup.get_text(" ", strip=True)[:20000])
    if m:
        total = int(m.group(1).replace(",", ""))
    return out, total


async def fetch_all(
    mnc: Any,
    client: httpx.AsyncClient,
    *,
    cap: int,
    net_keywords: list[str],
    title_predicate: TitlePredicate,
    host_sem: asyncio.Semaphore,
    log: Any,
) -> FetchResult:
    base = parse_base(mnc.api_url or mnc.pm_search_url)
    headers = {"Accept": "text/html,application/xhtml+xml"}

    def _page_fn(keyword: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            path = f"{base}/SearchJobs/{quote(keyword)}" if keyword else f"{base}/SearchJobs/"
            try:
                resp = await request(client, "GET", path, host_sem=host_sem, log=log, params={"jobOffset": offset}, headers=headers)
            except FetchError as exc:
                if offset == 0 and not keyword:
                    raise NotThisATS(f"{base} does not serve an Avature SearchJobs page: {exc}") from exc
                raise
            text = resp.text
            if looks_like_challenge(text) and "article--result" not in text:
                raise FetchError(f"challenge page at {path}")
            if offset == 0 and not keyword and "article--result" not in text and "avature" not in text.lower():
                # URL-shape hint only (…/SearchJobs): not an Avature site, or a JS stub → HTML lane
                raise NotThisATS(f"{base} has no Avature result markup")
            return parse_listing(text, base)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="avature:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"avature:net:{kw}")
            except FetchError as exc:
                log.warning("avature.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
