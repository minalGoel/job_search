"""Lever public postings API — the whole board in one call."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, request_json
from mnc_careers.ats.detect import parse_target

API = "https://api.lever.co/v0/postings/{slug}"


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
    slug = parse_target(mnc.api_url or mnc.pm_search_url, "lever")["slug"]
    if not slug:
        raise FetchError(f"cannot derive Lever slug from {mnc.api_url or mnc.pm_search_url}")
    data = await request_json(client, "GET", API.format(slug=slug), host_sem=host_sem, log=log, params={"mode": "json"})
    items = data if isinstance(data, list) else (data.get("data") or [])
    postings: list[RawPosting] = []
    for it in items:
        title = (it.get("text") or "").strip()
        url = it.get("hostedUrl") or it.get("applyUrl") or ""
        if not (title and url):
            continue
        cats = it.get("categories") or {}
        locs = [cats.get("location") or ""] + list(cats.get("allLocations") or [])
        location = "; ".join(dict.fromkeys(l for l in locs if l))
        postings.append(
            RawPosting(
                title=title, location=location, url=url,
                posted_on=str(it.get("createdAt") or ""),
                description=(it.get("descriptionPlain") or "")[:1500],
                external_id=str(it.get("id") or ""),
            )
        )
    return FetchResult(
        postings=postings[:cap], total_reported=len(items), pages=1,
        cap_hit=len(postings) > cap, strategy="lever:full",
    )
