"""Greenhouse boards API — the whole board in one call."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, request_json
from mnc_careers.ats.detect import parse_target

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


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
    board = parse_target(mnc.api_url or mnc.pm_search_url, "greenhouse")["board"]
    if not board:
        raise FetchError(f"cannot derive Greenhouse board from {mnc.api_url or mnc.pm_search_url}")
    # content=false keeps large boards light; descriptions are optional metadata.
    data = await request_json(client, "GET", API.format(board=board), host_sem=host_sem, log=log, params={"content": "false"})
    items = data.get("jobs") or []
    postings: list[RawPosting] = []
    for it in items:
        title = (it.get("title") or "").strip()
        url = it.get("absolute_url") or ""
        if not (title and url):
            continue
        loc = ((it.get("location") or {}).get("name") or "").strip()
        offices = [o.get("name") or "" for o in (it.get("offices") or []) if isinstance(o, dict)]
        location = loc or "; ".join(o for o in offices if o)
        postings.append(
            RawPosting(
                title=title, location=location, url=url,
                posted_on=it.get("updated_at") or it.get("first_published") or "",
                external_id=str(it.get("id") or ""),
            )
        )
    total = (data.get("meta") or {}).get("total")
    return FetchResult(
        postings=postings[:cap],
        total_reported=int(total) if isinstance(total, int) else len(items),
        pages=1,
        cap_hit=len(postings) > cap,
        strategy="greenhouse:full",
    )
