"""Eightfold career-site API (``/api/apply/v2/jobs``).

The server clamps ``num`` (often to 10) — pagination advances by what came
back. ``domain`` is taken from the registry URL's ``?domain=`` param when
present; many tenants also answer without it.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, merge, paginate, request_json
from mnc_careers.ats.detect import parse_target

PAGE_SIZE = 100


def _location(it: dict[str, Any]) -> str:
    locs = it.get("locations")
    if isinstance(locs, list) and locs:
        return "; ".join(str(l) for l in locs if l)
    return str(it.get("location") or "").strip()


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
    target = parse_target(mnc.api_url or mnc.pm_search_url, "eightfold")  # same URL shape as "eightfold"
    host, domain = target["host"], target["domain"]
    api = f"https://{host}/api/apply/v2/jobs"
    headers = {"Accept": "application/json", "Referer": f"https://{host}/careers"}

    def _page_fn(query: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            params: dict[str, Any] = {"start": offset, "num": PAGE_SIZE, "sort_by": "timestamp"}
            if domain:
                params["domain"] = domain
            if query:
                params["query"] = query
            data = await request_json(client, "GET", api, host_sem=host_sem, log=log, params=params, headers=headers)
            items = data.get("positions") or []
            batch: list[RawPosting] = []
            for it in items:
                title = (it.get("name") or "").strip()
                url = it.get("canonicalPositionUrl") or ""
                if not url and it.get("id"):
                    url = f"https://{host}/careers/job/{it['id']}"
                if not (title and url):
                    continue
                batch.append(
                    RawPosting(
                        title=title, location=_location(it), url=url,
                        posted_on=str(it.get("t_create") or it.get("t_update") or ""),
                        external_id=str(it.get("id") or ""),
                    )
                )
            total = data.get("count")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="eightfold:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"eightfold:net:{kw}")
            except FetchError as exc:
                log.warning("eightfold.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
