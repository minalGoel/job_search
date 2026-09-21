"""Phenom People career sites (``/{country}/{lang}/search-results``).

The page embeds its first 10 jobs in ``phApp.ddo`` and the real listing comes
from ``POST https://{host}/widgets`` with ``ddoKey="refineSearch"`` — which
honours ``size`` (100 works), ``from`` (offset) and ``keywords`` (our net), and
reports ``totalHits``. The request needs the site's ``lang`` (``siteConfig.
data.locale`` in the page HTML), a ``country`` (path segment) and any
``pageId``; a GET of the listing page first provides cookies + those values.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, NotThisATS, RawPosting, TitlePredicate, merge, paginate, request, request_json

PAGE_SIZE = 100
_LOCALE_RE = re.compile(r'"locale"\s*:\s*"([a-z]{2}_[a-z]{2,6})"', re.I)
_PAGEID_RE = re.compile(r'"pageId"\s*:\s*"(page\d+)"')
_SEARCH_PATH_RE = re.compile(r"^/(?:([a-z]{2,6})/([a-z]{2}(?:_[a-z]{2})?)/)?(?:job-)?search-results", re.I)


def site_params(url: str) -> dict[str, str]:
    """host + country/lang prefix from a Phenom listing URL."""
    parts = urlsplit(url)
    m = _SEARCH_PATH_RE.match(parts.path or "/")
    country = (m.group(1) or "global") if m else "global"
    lang = (m.group(2) or "en") if m else "en"
    prefix = f"/{m.group(1)}/{m.group(2)}" if (m and m.group(1)) else ""
    return {"host": parts.netloc, "country": country.lower(), "lang": lang.lower(), "prefix": prefix, "path": parts.path}


def _posting(host: str, prefix: str, it: dict[str, Any]) -> Optional[RawPosting]:
    title = (it.get("title") or "").strip()
    seq = it.get("jobSeqNo") or it.get("jobId") or ""
    url = it.get("applyUrl") or ""
    if not url and seq:
        url = f"https://{host}{prefix}/job/{seq}"
    if not (title and url):
        return None
    location = (it.get("cityStateCountry") or it.get("location") or "").strip()
    if not location:
        bits = [it.get("city"), it.get("state"), it.get("country")]
        location = ", ".join(str(b) for b in bits if b)
    if it.get("isMultiLocation") and isinstance(it.get("multi_location_array"), list):
        extra = [str(x.get("location", "")) for x in it["multi_location_array"] if isinstance(x, dict)]
        if extra:
            location = "; ".join(dict.fromkeys([location, *[e for e in extra if e]]))
    return RawPosting(
        title=title, location=location, url=url,
        posted_on=str(it.get("postedDate") or it.get("dateCreated") or ""),
        description=(it.get("descriptionTeaser") or "")[:1000],
        external_id=str(seq),
    )


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
    listing = mnc.api_url or mnc.pm_search_url
    sp = site_params(listing)
    host = sp["host"]
    page_url = f"https://{host}{sp['path']}"
    lang, page_id = f"{sp['lang']}_{sp['country']}", "page1"
    try:
        resp = await request(client, "GET", page_url, host_sem=host_sem, log=log, headers={"Accept": "text/html"})
        m = _LOCALE_RE.search(resp.text)
        if m:
            lang = m.group(1)
        m = _PAGEID_RE.search(resp.text)
        if m:
            page_id = m.group(1)
        if "phApp" not in resp.text[:200_000] and "phenom" not in resp.text[:200_000].lower():
            raise NotThisATS(f"{host} does not look like a Phenom site")
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.debug("phenom.warmup_failed", company=mnc.name, error=str(exc))

    widgets = f"https://{host}/widgets"
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Origin": f"https://{host}", "Referer": page_url}

    def _page_fn(keywords: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            body = {
                "lang": lang, "deviceType": "desktop", "country": sp["country"], "pageName": "search-results",
                "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": offset, "jobs": True, "counts": True,
                "all_fields": ["category", "country", "state", "city", "type"], "size": PAGE_SIZE, "clearAll": False,
                "jdsource": "facets", "isSliderEnable": False, "pageId": page_id, "siteType": "external",
                "keywords": keywords, "global": sp["country"] == "global", "selected_fields": {}, "locationData": {},
            }
            data = await request_json(client, "POST", widgets, host_sem=host_sem, log=log, json=body, headers=headers)
            rs = data.get("refineSearch") or {}
            items = (rs.get("data") or {}).get("jobs") or []
            batch = [p for p in (_posting(host, sp["prefix"], it) for it in items) if p]
            total = rs.get("totalHits")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="phenom:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"phenom:net:{kw}")
            except FetchError as exc:
                log.warning("phenom.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
