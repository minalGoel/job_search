"""SmartRecruiters public postings API (100 per page)."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from mnc_careers.ats.base import FetchError, FetchResult, RawPosting, TitlePredicate, merge, paginate, request_json
from mnc_careers.ats.detect import parse_target

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
PAGE_SIZE = 100


def _location(loc: dict[str, Any]) -> str:
    bits = [loc.get("city"), loc.get("region"), loc.get("country")]
    text = ", ".join(b for b in bits if b)
    if loc.get("remote"):
        text = f"{text} (Remote)" if text else "Remote"
    return text


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
    company = parse_target(mnc.api_url or mnc.pm_search_url, "smartrecruiters")["company"]
    if not company:
        raise FetchError(f"cannot derive SmartRecruiters company from {mnc.api_url or mnc.pm_search_url}")
    api = API.format(company=company)

    def _page_fn(q: str):
        async def _fetch_page(offset: int) -> tuple[list[RawPosting], Optional[int]]:
            params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
            if q:
                params["q"] = q
            data = await request_json(client, "GET", api, host_sem=host_sem, log=log, params=params)
            items = data.get("content") or []
            batch: list[RawPosting] = []
            for it in items:
                title = (it.get("name") or "").strip()
                pid = it.get("id") or ""
                if not (title and pid):
                    continue
                batch.append(
                    RawPosting(
                        title=title,
                        location=_location(it.get("location") or {}),
                        url=f"https://jobs.smartrecruiters.com/{company}/{pid}",
                        posted_on=it.get("releasedDate") or "",
                        external_id=str(pid),
                    )
                )
            total = data.get("totalFound")
            return batch, (int(total) if isinstance(total, int) else None)

        return _fetch_page

    result = await paginate(_page_fn(""), cap=cap, log=log, company=mnc.name, strategy="smartrecruiters:full")
    if result.cap_hit:
        for kw in net_keywords:
            try:
                extra = await paginate(_page_fn(kw), cap=cap, log=log, company=mnc.name, strategy=f"sr:net:{kw}")
            except FetchError as exc:
                log.warning("smartrecruiters.net_failed", company=mnc.name, keyword=kw, error=str(exc))
                continue
            merge(result, extra, f"net:{kw}")
    return result
