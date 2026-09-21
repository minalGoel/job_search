"""Amazon Jobs ``search.json`` (100 per page).

Amazon lists tens of thousands of roles globally, so the full listing always
hits the cap; the keyword net (``base_query``) is what actually finds PM
roles there. Local filtering still decides.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, merge, paginate, request_json

API = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE = 100


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
    headers = {"Accept": "application/json", "Referer": "https://www.amazon.jobs/en/search"}

    def _page_fn(base_query: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            params: dict[str, Any] = {"offset": offset, "result_limit": PAGE_SIZE, "sort": "recent"}
            if base_query:
                params["base_query"] = base_query
            data = await request_json(client, "GET", API, host_sem=host_sem, log=log, params=params, headers=headers)
            items = data.get("jobs") or []
            batch: list[RawPosting] = []
            for it in items:
                title = (it.get("title") or "").strip()
                path = it.get("job_path") or ""
                if not (title and path):
                    continue
                batch.append(
                    RawPosting(
                        title=title,
                        location=(it.get("location") or it.get("normalized_location") or "").strip(),
                        url=f"https://www.amazon.jobs{path}",
                        posted_on=it.get("posted_date") or "",
                        description=(it.get("description_short") or "")[:1500],
                        external_id=str(it.get("id_icims") or it.get("id") or ""),
                    )
                )
            total = data.get("hits")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="amazon:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"amazon:net:{kw}")
            except FetchError as exc:
                log.warning("amazon.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
