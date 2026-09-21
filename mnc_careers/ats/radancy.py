"""Radancy (TalentBrew) career sites (``/search-jobs``, e.g. jobs.intuit.com, jobs.citi.com).

The page's own AJAX endpoint ``GET {prefix}/search-jobs/results?...CurrentPage=N
&RecordsPerPage=50`` (with ``X-Requested-With: XMLHttpRequest``) returns JSON whose
``results`` field is an HTML fragment: ``<a href="/job/…"><h2>Title</h2>
<span class="job-location">Loc</span></a>`` plus ``data-total-results``. The full
parameter set below is required — trimmed requests return an empty fragment.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from mnc_careers.ats.base import FetchError, FetchResult, NotThisATS, RawPosting, TitlePredicate, merge, paginate, request_json

PAGE_SIZE = 50
_TOTAL_RE = re.compile(r'data-total-results="(\d+)"')


def parse_base(url: str) -> dict[str, str]:
    """host + path prefix up to and including ``/search-jobs``."""
    parts = urlsplit(url)
    path = parts.path or "/"
    i = path.lower().find("/search-jobs")
    prefix = path[: i + len("/search-jobs")] if i >= 0 else "/search-jobs"
    return {"host": parts.netloc, "prefix": prefix, "origin": f"{parts.scheme}://{parts.netloc}"}


_GENERIC_LOC = ("multiple locations", "multiple", "various", "")


def _city_from_path(href: str) -> str:
    """Radancy job paths are /job/{city-slug}/{title-slug}/{org}/{id} — the city is a
    usable location when the visible text is just "Multiple Locations"."""
    m = re.search(r"/job/([^/]+)/", href)
    return m.group(1).replace("-", " ").title() if m else ""


def parse_results_html(html: str, origin: str) -> list[RawPosting]:
    """Two skins: (a) <a href="/job/…"><h2>Title</h2><span class="job-location">…</span></a>
    (b) <li class="sr-job-item"><h3><a class="sr-job-item__link">Title</a></h3><span class="sr-job-location">…</span></li>."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawPosting] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='/job/']"):
        href = a.get("href", "")
        if not href or href in seen:
            continue
        h = a.select_one("h2, h3") or a.select_one("[class*='title']")
        title = (h.get_text(strip=True) if h else a.get("data-title") or a.get_text(" ", strip=True) or "").strip()
        container = a.find_parent(["li", "article", "div"]) or a
        loc_el = a.select_one("span.job-location, [class*='location']") or container.select_one("[class*='location']")
        location = loc_el.get_text(" ", strip=True) if loc_el else ""
        if location.lower() in _GENERIC_LOC:
            location = _city_from_path(href) or location
        if title and href:
            seen.add(href)
            out.append(RawPosting(title=title, location=location, url=urljoin(origin, href), external_id=a.get("data-job-id", "") or ""))
    return out


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
    b = parse_base(mnc.api_url or mnc.pm_search_url)
    api = f"{b['origin']}{b['prefix']}/results"
    headers = {"Accept": "application/json, text/javascript, */*", "X-Requested-With": "XMLHttpRequest",
               "Referer": f"{b['origin']}{b['prefix']}"}

    def _page_fn(keywords: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            page = offset // PAGE_SIZE + 1
            params = {
                "ActiveFacetID": 0, "CurrentPage": page, "RecordsPerPage": PAGE_SIZE, "Distance": 50, "RadiusUnitType": 0,
                "Keywords": keywords, "Location": "", "ShowRadius": "False", "IsPagination": "True" if page > 1 else "False",
                "CustomFacetName": "", "FacetTerm": "", "FacetType": 0, "SearchResultsModuleName": "Search Results",
                "SearchFiltersModuleName": "Search Filters", "SortCriteria": 0, "SortDirection": 0, "SearchType": 5,
                "PostalCode": "", "ResultsType": 0, "fc": "", "fl": "", "fcf": "", "afc": "", "afl": "", "afcf": "",
            }
            try:
                data = await request_json(client, "GET", api, host_sem=host_sem, log=log, params=params, headers=headers)
            except FetchError as exc:
                if page == 1 and not keywords:
                    # /search-jobs is only a URL-shape hint; a site that doesn't answer the
                    # Radancy results endpoint (404/403/500/non-JSON) isn't Radancy.
                    raise NotThisATS(f"{b['host']} does not answer the Radancy results endpoint: {exc}") from exc
                raise
            html = data.get("results") or ""
            if not isinstance(html, str):
                raise NotThisATS(f"unexpected payload at {api} — not Radancy")
            batch = parse_results_html(html, b["origin"])
            m = _TOTAL_RE.search(html)
            return batch, (int(m.group(1)) if m else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="radancy:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"radancy:net:{kw}")
            except FetchError as exc:
                log.warning("radancy.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
