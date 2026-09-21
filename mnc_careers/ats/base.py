"""Shared types and HTTP helper for typed ATS fetchers.

Every fetcher exposes::

    async def fetch_all(mnc, client, *, cap, net_keywords, title_predicate,
                        host_sem, log) -> FetchResult

and returns *raw postings* only. No title or location filtering happens
here — that is done once, in ``mnc_careers/filter.py`` via the shared
``services.title_filter`` / ``services.location_filter`` (the user's rule:
we fetch everything and filter locally; portal search is never trusted).

``title_predicate`` is passed so a fetcher can avoid *expensive per-posting
follow-ups* (e.g. Workday's job-detail call to resolve "3 Locations") for
titles that would be rejected anyway. It must never be used to drop
postings from the result.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

import httpx

TitlePredicate = Callable[[str], bool]

_RETRY_STATUS = {429, 500, 502, 503, 504}
_BLOCK_STATUS = {401, 403}
_CHALLENGE_MARKERS = ("cf-chl", "Just a moment", "Access Denied", "_Incapsula_Resource", "akamai")


@dataclass
class RawPosting:
    title: str
    location: str
    url: str
    posted_on: str = ""
    description: str = ""
    external_id: str = ""
    # Structured detail a fetcher already has for this posting (a services.job_detail.DetailRecord),
    # e.g. Workday's per-job CXS record — so the gate never fetches the same URL twice.
    detail: Any = None


@dataclass
class FetchResult:
    postings: list[RawPosting] = field(default_factory=list)
    total_reported: Optional[int] = None
    pages: int = 0
    cap_hit: bool = False
    strategy: str = ""
    error: str = ""
    json_postings: int = 0  # HTML lane: how many came from intercepted JSON (strong signal)


class FetchError(Exception):
    """A request failed in a way retries won't fix (401/403, challenge page,
    exhausted retries, unparseable body)."""


class NotThisATS(FetchError):
    """The URL *looked* like this ATS (heuristic detection) but the site isn't.
    The orchestrator reroutes such companies to the HTML lane."""


class Fetcher(Protocol):
    async def fetch_all(  # noqa: D102
        self,
        mnc: Any,
        client: httpx.AsyncClient,
        *,
        cap: int,
        net_keywords: list[str],
        title_predicate: TitlePredicate,
        host_sem: asyncio.Semaphore,
        log: Any,
    ) -> FetchResult: ...


def looks_like_challenge(text: str) -> bool:
    head = text[:4000]
    return any(m in head for m in _CHALLENGE_MARKERS)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    host_sem: asyncio.Semaphore,
    log: Any,
    attempts: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """One HTTP request with per-host throttling and bounded retries.

    Retries (1s/3s/9s) on 429, 5xx, timeouts and transport errors. Raises
    ``FetchError`` on 401/403, on any other 4xx, or when retries are exhausted.
    """
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with host_sem:
                resp = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            log.debug("ats.request_retry", url=url, attempt=attempt, error=type(exc).__name__)
        else:
            if resp.status_code in _BLOCK_STATUS:
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            if resp.status_code in _RETRY_STATUS:
                last_exc = FetchError(f"HTTP {resp.status_code} for {url}")
                log.debug("ats.request_retry", url=url, attempt=attempt, status=resp.status_code)
            elif resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            else:
                return resp
        if attempt < attempts:
            await asyncio.sleep(delay)
            delay *= 3
    raise FetchError(f"retries exhausted for {url}: {last_exc}")


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    host_sem: asyncio.Semaphore,
    log: Any,
    **kwargs: Any,
) -> Any:
    """``request`` + JSON decode; a challenge/HTML body raises ``FetchError``."""
    resp = await request(client, method, url, host_sem=host_sem, log=log, **kwargs)
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    if "json" not in ctype and looks_like_challenge(text):
        raise FetchError(f"challenge page instead of JSON at {url}")
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(f"non-JSON body at {url}: {exc}") from exc


async def paginate(
    fetch_page: Callable[[int], Awaitable[tuple[list[RawPosting], Optional[int]]]],
    *,
    cap: int,
    log: Any,
    company: str,
    strategy: str,
) -> FetchResult:
    """Generic offset pagination.

    ``fetch_page(offset)`` returns ``(postings, total_reported)``. We advance
    the offset by **what was actually returned** (servers clamp page sizes),
    stop on an empty page, when ``total`` is reached, or at ``cap``.
    """
    postings: list[RawPosting] = []
    seen: set[str] = set()
    offset = 0
    pages = 0
    total: Optional[int] = None
    while True:
        batch, reported = await fetch_page(offset)
        pages += 1
        # Trust the first page's total: Workday reports it only at offset 0
        # (later pages say 0), and some APIs recount per page.
        if reported is not None and (total is None or pages == 1):
            total = reported
        if not batch:
            break
        new = 0
        for p in batch:
            key = p.url or f"{p.title}|{p.location}"
            if key not in seen:
                seen.add(key)
                postings.append(p)
                new += 1
        offset += len(batch)
        if new == 0:  # server ignored the offset — avoid looping forever
            log.debug("ats.pagination_stalled", company=company, offset=offset)
            break
        if total is not None and offset >= total:
            break
        if offset >= cap:
            break
    cap_hit = total is not None and total > cap and offset >= cap
    if cap_hit:
        log.warning("mnc.cap_hit", company=company, total=total, cap=cap, strategy=strategy)
    return FetchResult(postings=postings, total_reported=total, pages=pages, cap_hit=cap_hit, strategy=strategy)


def merge(primary: FetchResult, extra: FetchResult, strategy_suffix: str) -> FetchResult:
    """Merge a supplementary (net) fetch into the primary result, deduping by URL."""
    seen = {p.url for p in primary.postings if p.url}
    added = 0
    for p in extra.postings:
        if p.url and p.url in seen:
            continue
        seen.add(p.url)
        primary.postings.append(p)
        added += 1
    primary.pages += extra.pages
    primary.strategy = f"{primary.strategy}+{strategy_suffix}({added})"
    return primary
