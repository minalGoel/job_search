"""SAP SuccessFactors career sites (``.../search/?q=&startrow=N``), httpx + BS4.

Two flavours, decided from the first ``/search/`` page:

* **classic** — 25 server-rendered ``a.jobTitle-link`` rows per page; total in
  ``span.paginationLabel`` ("Results 1 – 25 of 1234").
* **Unify** (Career Site Builder) — no rows in the HTML; results come from
  ``POST /services/recruiting/v1/jobs`` (10 per page, ``totalJobs``) with the
  tenant's ``locale`` (``currentLocale`` in the page).

Akamai-fronted tenants answer 403 to httpx — that surfaces as ``FetchError``
and discovery then pins ``api_type="html"``.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, looks_like_challenge, merge, paginate, request, request_json
from mnc_careers.ats.detect import parse_target

PAGE_SIZE = 25
UNIFY_PAGE_SIZE = 10
_LOCALE_RE = re.compile(r"(?:currentLocale|defaultLocale)\s*:\s*'([a-z]{2}_[A-Z]{2})'")
_TOTAL_RE = re.compile(r"of\s+([\d,]+)", re.I)


def parse_listing(html: str, base: str) -> tuple[list[RawPosting], Optional[int]]:
    """Pure HTML → postings (+ total when the pagination label is present)."""
    soup = BeautifulSoup(html, "html.parser")
    postings: list[RawPosting] = []
    rows = soup.select("tr.data-row") or soup.select("li.job-tile") or soup.select("div.job-tile")
    if rows:
        for row in rows:
            a = row.select_one("a.jobTitle-link") or row.select_one("a[href*='/job/']")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            loc_el = row.select_one("span.jobLocation") or row.select_one("[class*='location']")
            location = loc_el.get_text(" ", strip=True) if loc_el else ""
            date_el = row.select_one("span.jobDate") or row.select_one("[class*='date']")
            if title and href:
                postings.append(RawPosting(title=title, location=location, url=href,
                                           posted_on=date_el.get_text(strip=True) if date_el else ""))
    else:
        # Flat layout: anchors + sibling location spans
        for a in soup.select("a.jobTitle-link"):
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            parent = a.find_parent(["tr", "li", "div"])
            loc_el = parent.select_one("span.jobLocation") if parent else None
            if title and href:
                postings.append(RawPosting(title=title, location=loc_el.get_text(" ", strip=True) if loc_el else "", url=href))
    total: Optional[int] = None
    label = soup.select_one("span.paginationLabel") or soup.select_one(".paginationLabel")
    if label:
        m = _TOTAL_RE.search(label.get_text(" ", strip=True))
        if m:
            total = int(m.group(1).replace(",", ""))
    return postings, total


def _unify_posting(origin: str, locale: str, resp: dict[str, Any]) -> Optional[RawPosting]:
    title = (resp.get("unifiedStandardTitle") or resp.get("title") or "").strip()
    rid = resp.get("id") or ""
    if not (title and rid):
        return None
    locs = resp.get("jobLocationShort") or []
    if not locs:
        locs = [", ".join(str(resp.get(k)) for k in ("custprimecity", "custCountryRegion") if resp.get(k))]
    location = "; ".join(dict.fromkeys(str(l).strip(" ,") for l in locs if str(l).strip(" ,")))
    return RawPosting(
        title=title, location=location,
        url=f"{origin}/job/{title.replace(' ', '-')}/{rid}-{locale}",
        posted_on=str(resp.get("unifiedStandardStart") or ""), external_id=str(rid),
    )


async def _fetch_unify(mnc: Any, client: httpx.AsyncClient, *, base: str, page_html: str, cap: int, net_keywords: list[str],
                       host_sem: asyncio.Semaphore, log: Any) -> FetchResult:
    """SuccessFactors Career Site Builder "Unify": results come from
    ``POST /services/recruiting/v1/jobs`` (10 per page), not from the HTML."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    m = _LOCALE_RE.search(page_html)
    locale = m.group(1) if m else "en_US"
    api = f"{origin}/services/recruiting/v1/jobs"
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Referer": base}

    def _page_fn(keywords: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            body = {"keywords": keywords, "locale": locale, "location": "", "pageNumber": offset // UNIFY_PAGE_SIZE, "sortBy": "recent"}
            data = await request_json(client, "POST", api, host_sem=host_sem, log=log, json=body, headers=headers)
            items = data.get("jobSearchResult") or []
            batch = [p for p in (_unify_posting(origin, locale, it.get("response") or {}) for it in items) if p]
            total = data.get("totalJobs")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="sf_unify:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"sf_unify:net:{kw}")
            except FetchError as exc:
                log.warning("sf_unify.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result


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
    base = parse_target(mnc.api_url or mnc.pm_search_url, "successfactors")["base"]
    headers = {"Accept": "text/html,application/xhtml+xml"}

    # The first page decides the flavour: classic server-rendered rows, or the
    # client-rendered "Unify" builder (jobResultsCard config, no rows).
    first = await request(client, "GET", base, host_sem=host_sem, log=log,
                          params={"q": "", "startrow": 0, "sortColumn": "referencedate", "sortDirection": "desc"}, headers=headers)
    if looks_like_challenge(first.text) and "jobTitle-link" not in first.text and "jobResultsCard" not in first.text:
        raise FetchError(f"challenge page at {base}")
    if "jobTitle-link" not in first.text and ("jobResultsCard" in first.text or "j2w.SearchResultsUnify" in first.text):
        log.info("successfactors.unify_detected", company=mnc.name)
        return await _fetch_unify(mnc, client, base=base, page_html=first.text, cap=cap, net_keywords=net_keywords, host_sem=host_sem, log=log)

    def _page_fn(q: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            if offset == 0 and not q:
                return parse_listing(first.text, base)
            params = {"q": q, "startrow": offset, "sortColumn": "referencedate", "sortDirection": "desc"}
            resp = await request(client, "GET", base, host_sem=host_sem, log=log, params=params, headers=headers)
            if looks_like_challenge(resp.text) and "jobTitle-link" not in resp.text:
                raise FetchError(f"challenge page at {base}")
            return parse_listing(resp.text, base)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="successfactors:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"sf:net:{kw}")
            except FetchError as exc:
                log.warning("successfactors.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
