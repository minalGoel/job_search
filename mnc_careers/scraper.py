"""MNC careers orchestrator — fetch every company's full listing, filter locally.

Two lanes run concurrently:

* **API lane** (httpx): companies whose ``ats_type`` has a typed fetcher in
  ``mnc_careers/ats``. One shared ``AsyncClient``; ``MNC_API_CONCURRENCY``
  companies at a time with ``MNC_PER_HOST_CONCURRENCY`` requests per host.
* **HTML lane** (Playwright): everything else via ``html_generic``.

Every company runs under ``asyncio.wait_for(MNC_COMPANY_TIMEOUT)`` and
``gather(return_exceptions=True)`` so one broken portal can never abort the
rest. Results are ``(jobs, [MNCRunResult])`` — the per-company outcomes are
persisted in ``source_runs`` by ``main._run_mnc_jobs`` so we can see which of
~350 portals need attention.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
import structlog

from browser.context import BrowserManager
from config.settings import Settings
from models.job import Job
from mnc_careers import html_generic
from mnc_careers.ats import FETCHERS, FetchError, FetchResult, NotThisATS, strip_search_params
from mnc_careers.ats.base import RawPosting
from mnc_careers.filter import postings_to_jobs
from mnc_careers.registry import MNC, MNC_REGISTRY
from services.job_detail import DetailRecord, fetch_detail
from services.location_resolver import needs_detail
from services.scoring import _company_slug
from services.title_filter import current_params, is_relevant_title

log = structlog.get_logger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class MNCRunResult:
    name: str
    ats: str
    lane: str  # "api" | "html"
    status: str  # "ok" | "empty" | "failed"
    fetched: int = 0
    total_reported: Optional[int] = None
    pages: int = 0
    cap_hit: bool = False
    matched: int = 0
    error: str = ""
    duration_ms: int = 0
    strategy: str = ""
    detail_fetched: int = 0    # structured detail requests made at the gate
    detail_blocked: int = 0    # …that were refused (403/challenge)
    detail_used: int = 0       # postings judged with a structured record

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def select_targets(
    registry: list[MNC],
    *,
    only: Optional[list[str]] = None,
    ats: Optional[str] = None,
    aliases: Optional[dict[str, str]] = None,
) -> list[MNC]:
    """Entries with a listing/API URL, optionally narrowed by name or ATS."""
    targets = [m for m in registry if m.pm_search_url or m.api_url]
    if ats:
        targets = [m for m in targets if (m.ats_type or "html") == ats]
    if only:
        wanted: set[str] = set()
        for raw in only:
            raw = raw.strip()
            if not raw:
                continue
            wanted.add(_company_slug((aliases or {}).get(raw, raw)))
        # whole-word match so "SAP" does not select "Publicis Sapient"
        patterns = [re.compile(rf"\b{re.escape(w.strip().lower())}\b") for w in only if w.strip()]
        targets = [
            m for m in targets
            if _company_slug(m.name) in wanted or any(p.search(m.name.lower()) for p in patterns)
        ]
    return targets


class MNCCareerScraper:
    """Scrapes MNC careers portals for target roles in Delhi NCR."""

    def __init__(self, browser_manager: Optional[BrowserManager], settings: Optional[Settings] = None) -> None:
        self.bm = browser_manager
        self.settings = settings or Settings()
        self._log = log.bind(module="mnc_careers")
        self._host_sems: dict[str, asyncio.Semaphore] = {}
        self._client: Optional[httpx.AsyncClient] = None
        # Job.id → job_enrichment columns for every matched job (structured detail + verdict);
        # main._run_mnc_jobs upserts these after insert_job, for new *and* existing ids.
        self.enrichment: dict[str, dict] = {}

    # ------------------------------------------------------------------
    def _host_sem(self, url: str) -> asyncio.Semaphore:
        host = urlsplit(url).netloc
        sem = self._host_sems.get(host)
        if sem is None:
            sem = asyncio.Semaphore(self.settings.MNC_PER_HOST_CONCURRENCY)
            self._host_sems[host] = sem
        return sem

    async def scrape_all(
        self,
        *,
        only: Optional[list[str]] = None,
        ats: Optional[str] = None,
        cap: Optional[int] = None,
        aliases: Optional[dict[str, str]] = None,
    ) -> tuple[list[Job], list[MNCRunResult]]:
        targets = select_targets(MNC_REGISTRY, only=only, ats=ats, aliases=aliases)
        cap = cap or self.settings.MNC_MAX_POSTINGS
        api_targets = [m for m in targets if m.ats_type in FETCHERS]
        html_targets = [m for m in targets if m.ats_type not in FETCHERS]
        self._log.info("mnc.starting", companies=len(targets), api_lane=len(api_targets), html_lane=len(html_targets), cap=cap)

        # One httpx client for the whole run: the API lane, the HTML lane's detail requests
        # and the gate share it (cookie jar is domain-scoped; limits sized for the API lane).
        limits = httpx.Limits(max_connections=self.settings.MNC_API_CONCURRENCY * 2, max_keepalive_connections=self.settings.MNC_API_CONCURRENCY)
        headers = {"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=self.settings.MNC_HTTP_TIMEOUT, limits=limits) as client:
            self._client = client
            try:
                return await self._scrape_all(targets, api_targets, html_targets, cap)
            finally:
                self._client = None

    async def _scrape_all(self, targets: list[MNC], api_targets: list[MNC], html_targets: list[MNC], cap: int) -> tuple[list[Job], list[MNCRunResult]]:
        # API lane first: companies whose ATS was mis-detected from the URL shape
        # (NotThisATS) are rerouted to the HTML lane, which then runs once.
        jobs: list[Job] = []
        results: list[MNCRunResult] = []
        api_jobs, api_res = await self._api_lane(api_targets, cap)
        jobs.extend(api_jobs)
        rerouted: list[MNC] = []
        for r in api_res:
            if r.status == "failed" and r.error.startswith("NotThisATS:"):
                m = next((x for x in api_targets if x.name == r.name), None)
                if m is not None:
                    rerouted.append(m)
                    self._log.info("mnc.rerouted_to_html", company=m.name, reason=r.error)
                    continue
            results.append(r)
        html_targets = html_targets + rerouted
        if html_targets:
            if self.bm is None:
                self._log.warning("mnc.html_lane_skipped", reason="no browser", companies=len(html_targets))
                for m in html_targets:
                    results.append(MNCRunResult(m.name, m.ats_type or "html", "html", "failed", error="no browser available"))
            else:
                html_jobs, html_res = await self._html_lane(html_targets)
                jobs.extend(html_jobs)
                results.extend(html_res)
        order = {m.name: i for i, m in enumerate(targets)}
        results.sort(key=lambda r: order.get(r.name, 1 << 30))
        return jobs, results

    # ------------------------------------------------------------------
    async def _api_lane(self, mncs: list[MNC], cap: int) -> tuple[list[Job], list[MNCRunResult]]:
        if not mncs:
            return [], []
        sem = asyncio.Semaphore(self.settings.MNC_API_CONCURRENCY)
        net_keywords = list(current_params().server_net_keywords)
        client = self._client
        assert client is not None

        async def _one(mnc: MNC) -> tuple[list[Job], MNCRunResult]:
            async with sem:
                fetcher = FETCHERS[mnc.ats_type]
                url = mnc.api_url or mnc.pm_search_url

                async def _fetch() -> FetchResult:
                    return await fetcher(
                        mnc, client, cap=cap, net_keywords=net_keywords,
                        title_predicate=is_relevant_title,
                        host_sem=self._host_sem(url), log=self._log.bind(company=mnc.name),
                    )

                return await self._run_one(mnc, _fetch, lane="api")

        return await self._gather(mncs, _one, lane="api")

    async def _html_lane(self, mncs: list[MNC]) -> tuple[list[Job], list[MNCRunResult]]:
        assert self.bm is not None
        sem = asyncio.Semaphore(self.settings.MNC_HTML_CONCURRENCY)
        cookies_dir = self.settings.COOKIES_DIR

        async def _one(mnc: MNC) -> tuple[list[Job], MNCRunResult]:
            async with sem:
                raw_url = mnc.pm_search_url or mnc.api_url
                listing_url = strip_search_params(raw_url)

                async def _fetch() -> FetchResult:
                    return await html_generic.fetch_all(
                        mnc, self.bm, cookies_dir=cookies_dir,
                        max_pages=self.settings.MNC_HTML_MAX_PAGES,
                        listing_url=listing_url, net_url=raw_url,
                        log=self._log.bind(company=mnc.name),
                    )

                return await self._run_one(mnc, _fetch, lane="html")

        return await self._gather(mncs, _one, lane="html")

    async def _gather(self, mncs: list[MNC], one, *, lane: str) -> tuple[list[Job], list[MNCRunResult]]:  # noqa: ANN001
        outcomes = await asyncio.gather(*(one(m) for m in mncs), return_exceptions=True)
        jobs: list[Job] = []
        results: list[MNCRunResult] = []
        for mnc, out in zip(mncs, outcomes):
            if isinstance(out, BaseException):
                # _run_one already catches everything; this is the belt to its braces.
                results.append(MNCRunResult(mnc.name, mnc.ats_type or "html", lane, "failed", error=f"{type(out).__name__}: {out}"[:300]))
                self._log.error("mnc.failed", company=mnc.name, lane=lane, error=str(out)[:200])
                continue
            lane_jobs, res = out
            jobs.extend(lane_jobs)
            results.append(res)
        return jobs, results

    async def _resolve_details(self, mnc: MNC, postings: list[RawPosting], res: MNCRunResult) -> dict[str, DetailRecord]:
        """Fetch the structured detail record for title-passing postings whose listing
        location is coarse or already passes (services.location_resolver.needs_detail).
        Postings that name a specific non-NCR place are left alone — the listing is right
        about that. Returns url → DetailRecord; never raises."""
        client = self._client
        if client is None:
            return {}
        seen: set[str] = set()
        todo: list[RawPosting] = []
        for p in postings:
            url = (p.url or "").strip()
            if not url or url in seen or not (p.title or "").strip():
                continue
            seen.add(url)
            if isinstance(p.detail, DetailRecord) and p.detail.status == "ok":
                continue  # the fetcher already has it (Workday "N Locations")
            if is_relevant_title(p.title) and needs_detail(p.location or ""):
                todo.append(p)
        if not todo:
            return {}
        sem = asyncio.Semaphore(4)
        out: dict[str, DetailRecord] = {}
        log = self._log.bind(company=mnc.name)

        async def _one(p: RawPosting) -> None:
            async with sem:
                rec = await fetch_detail(p.url, client, host_sem=self._host_sem(p.url), log=log)
            res.detail_fetched += 1
            if rec.status == "blocked":
                res.detail_blocked += 1
            out[p.url] = rec

        await asyncio.gather(*(_one(p) for p in todo))
        log.info("mnc.details", requested=len(todo), ok=sum(r.status == "ok" for r in out.values()), blocked=res.detail_blocked)
        return out

    async def _run_one(self, mnc: MNC, fetch, *, lane: str) -> tuple[list[Job], MNCRunResult]:  # noqa: ANN001
        """Never raises: times the fetch, applies local filters, classifies the outcome."""
        ats = mnc.ats_type or "html"
        started = time.monotonic()
        res = MNCRunResult(mnc.name, ats, lane, "failed")
        try:
            fr: FetchResult = await asyncio.wait_for(fetch(), timeout=self.settings.MNC_COMPANY_TIMEOUT)
        except asyncio.TimeoutError:
            res.error = f"timeout after {self.settings.MNC_COMPANY_TIMEOUT}s"
        except NotThisATS as exc:
            res.error = f"NotThisATS: {exc}"[:300]
        except FetchError as exc:
            res.error = str(exc)[:300]
        except Exception as exc:  # noqa: BLE001
            res.error = f"{type(exc).__name__}: {exc}"[:300]
            self._log.exception("mnc.unexpected", company=mnc.name, lane=lane)
        else:
            # Structured detail for coarse-or-passing listings, under its own budget: a slow
            # detail phase must never throw away the listing result we already have.
            details: dict[str, DetailRecord] = {}
            try:
                details = await asyncio.wait_for(self._resolve_details(mnc, fr.postings, res), timeout=self.settings.MNC_DETAIL_TIMEOUT)
            except asyncio.TimeoutError:
                self._log.warning("mnc.detail_timeout", company=mnc.name, fetched=res.detail_fetched, budget_s=self.settings.MNC_DETAIL_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                self._log.warning("mnc.detail_failed", company=mnc.name, error=str(exc)[:200])
            jobs, stats = postings_to_jobs(mnc, fr.postings, log=self._log, details=details)
            self.enrichment.update(stats.enrichment)
            res.detail_used = stats.detail_used
            res.fetched = stats.fetched
            res.total_reported = fr.total_reported
            res.pages = fr.pages
            res.cap_hit = fr.cap_hit
            res.matched = stats.matched
            res.strategy = fr.strategy
            res.status = "ok" if stats.fetched else "empty"
            res.duration_ms = int((time.monotonic() - started) * 1000)
            self._log.info(
                "mnc.fetched", company=mnc.name, ats=ats, lane=lane, fetched=stats.fetched,
                total=fr.total_reported, pages=fr.pages, cap_hit=fr.cap_hit,
                title_rejected=stats.title_rejected, location_rejected=stats.location_rejected,
                matched=stats.matched, ms=res.duration_ms,
            )
            return jobs, res
        res.duration_ms = int((time.monotonic() - started) * 1000)
        self._log.warning("mnc.failed", company=mnc.name, ats=ats, lane=lane, error=res.error, ms=res.duration_ms)
        return [], res
