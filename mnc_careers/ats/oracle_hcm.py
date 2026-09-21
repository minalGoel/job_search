"""Oracle Recruiting Cloud (HCM) candidate-experience sites.

Listing: ``GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions``
with ``finder=findReqs;siteNumber={site},limit=N,offset=N,sortBy=POSTING_DATES_DESC``
(``keyword="…"`` inside the finder for the cap-hit net). Response:
``items[0].TotalJobsCount`` and ``items[0].requisitionList[]`` with
``Id, Title, PrimaryLocation, secondaryLocations[].Name, PostedDate,
WorkplaceType``. Job URL: ``/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}``.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, merge, paginate, request_json

PAGE_SIZE = 100
_SITE_RE = re.compile(r"/hcmUI/CandidateExperience/([a-z]{2}(?:-[A-Za-z]{2})?)/sites/([A-Za-z0-9_]+)", re.I)


def parse_site(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    m = _SITE_RE.search(parts.path or "")
    lang, site = (m.group(1), m.group(2)) if m else ("en", "CX_1")
    return {"host": parts.netloc, "lang": lang, "site": site}


def _posting(host: str, lang: str, site: str, it: dict[str, Any]) -> Optional[RawPosting]:
    title = (it.get("Title") or "").strip()
    rid = it.get("Id") or ""
    if not (title and rid):
        return None
    locs = [it.get("PrimaryLocation") or ""]
    for sec in it.get("secondaryLocations") or []:
        if isinstance(sec, dict) and sec.get("Name"):
            locs.append(sec["Name"])
    location = "; ".join(dict.fromkeys(l for l in locs if l))
    wp = it.get("WorkplaceType")
    if wp and str(wp).lower() in ("remote", "hybrid") and str(wp).lower() not in location.lower():
        location = f"{location} ({wp})" if location else str(wp)
    return RawPosting(
        title=title, location=location,
        url=f"https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/job/{rid}",
        posted_on=str(it.get("PostedDate") or ""), external_id=str(rid),
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
    sp = parse_site(mnc.api_url or mnc.pm_search_url)
    host, lang, site = sp["host"], sp["lang"], sp["site"]
    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    headers = {"Accept": "application/json", "Referer": f"https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/jobs"}

    def _page_fn(keyword: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            finder = f"findReqs;siteNumber={site},limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
            if keyword:
                finder += f',keyword="{keyword}"'
            params = {"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder}
            data = await request_json(client, "GET", api, host_sem=host_sem, log=log, params=params, headers=headers)
            items = data.get("items") or []
            if not items:
                return [], None
            head = items[0]
            reqs = head.get("requisitionList") or []
            batch = [p for p in (_posting(host, lang, site, it) for it in reqs) if p]
            total = head.get("TotalJobsCount")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="oracle_hcm:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"oracle:net:{kw}")
            except FetchError as exc:
                log.warning("oracle_hcm.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
