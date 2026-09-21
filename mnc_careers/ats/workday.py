"""Workday CXS fetcher.

Primary: ``POST https://{host}/wday/cxs/{tenant}/{site}/jobs`` with an empty
``searchText`` — the *full* listing, 20 per page (Workday's hard limit),
paginated to ``cap``. Only when the tenant reports more postings than the cap
do we additionally run one keyword-narrowed query per ``net_keywords`` and
merge (the "net"); local filtering still decides.

``locationsText`` for multi-site postings is literally ``"3 Locations"``.
For postings whose *title* passes ``title_predicate`` we resolve the real
locations via the job-detail endpoint; otherwise the raw text is kept (and
the location filter rejects it, as it should for an unknown location).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from mnc_careers.ats.base import (
    FetchError,
    FetchResult,
    RawPosting,
    TitlePredicate,
    merge,
    paginate,
    request,
    request_json,
)
from mnc_careers.ats.detect import parse_target

PAGE_SIZE = 20
_MULTI_LOC_RE = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
_DETAIL_CONCURRENCY = 4


def _headers(host: str, site: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": f"https://{host}",
        "Referer": f"https://{host}/{site}",
    }


def _posting(host: str, site: str, item: dict[str, Any]) -> Optional[RawPosting]:
    title = (item.get("title") or "").strip()
    path = item.get("externalPath") or ""
    if not title or not path:
        return None
    return RawPosting(
        title=title,
        location=(item.get("locationsText") or "").strip(),
        url=f"https://{host}/{site}{path}",
        posted_on=item.get("postedOn") or "",
        external_id=(item.get("bulletFields") or [""])[0] if item.get("bulletFields") else "",
    )


async def _resolve_locations(
    client: httpx.AsyncClient,
    host: str,
    tenant: str,
    site: str,
    postings: list[RawPosting],
    *,
    host_sem: asyncio.Semaphore,
    log: Any,
) -> None:
    """Replace "N Locations" with the real list for the given postings (in place)."""
    sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

    async def _one(p: RawPosting) -> None:
        external_path = p.url.split(f"/{site}", 1)[1] if f"/{site}" in p.url else ""
        if not external_path:
            return
        url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
        try:
            async with sem:
                data = await request_json(client, "GET", url, host_sem=host_sem, log=log, headers=_headers(host, site))
        except FetchError as exc:
            log.debug("workday.detail_failed", url=url, error=str(exc))
            return
        info = data.get("jobPostingInfo") or {}
        locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
        locs = [l for l in locs if l]
        if locs:
            p.location = "; ".join(locs)
            if not p.description:
                p.description = re.sub(r"<[^>]+>", " ", info.get("jobDescription") or "")[:1500].strip()
        try:
            from services.job_detail import parse_workday_detail  # local import: keeps ats/ free of services at import time

            rec = parse_workday_detail(data)
            if rec is not None:
                rec.url = url
                p.detail = rec
        except Exception as exc:  # noqa: BLE001 — detail is a bonus, never a failure
            log.debug("workday.detail_parse_failed", url=url, error=str(exc))

    await asyncio.gather(*(_one(p) for p in postings))


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
    target = parse_target(mnc.api_url or mnc.pm_search_url, "workday")
    host, tenant, site = target["host"], target["tenant"], target["site"]
    if not site:
        raise FetchError(f"cannot derive Workday site from {mnc.pm_search_url}")
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = _headers(host, site)

    # Cookie warm-up: the CXS endpoint expects a session from the site root.
    try:
        await request(client, "GET", f"https://{host}/{site}", host_sem=host_sem, log=log, headers={"Accept": "text/html"})
    except FetchError as exc:
        log.debug("workday.warmup_failed", company=mnc.name, error=str(exc))

    def _page_fn(search_text: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            body = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": search_text}
            data = await request_json(client, "POST", api, host_sem=host_sem, log=log, json=body, headers=headers)
            items = data.get("jobPostings") or []
            total = data.get("total")
            batch = [p for p in (_posting(host, site, it) for it in items) if p]
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="workday:full")

    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"workday:net:{kw}")
            except FetchError as exc:
                log.warning("workday.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")

    # Resolve "N Locations" only for postings whose title we would keep.
    multi = [p for p in result.postings if _MULTI_LOC_RE.match(p.location) and title_predicate(p.title)]
    if multi:
        log.info("workday.resolving_locations", company=mnc.name, count=len(multi))
        await _resolve_locations(client, host, tenant, site, multi, host_sem=host_sem, log=log)
    return result
