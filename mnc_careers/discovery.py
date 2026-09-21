"""Discover careers-portal listing endpoints for companies in the MNC input CSV.

Pipeline (``python main.py mnc-discover``):

1. ``classify_against_registry`` — each CSV row is ``exact`` (slug match),
   ``alias`` (in ``CSV_ALIASES``) or ``new``. Fuzzy similarity is reported as
   ``possible_alias`` but NEVER auto-folded (Fidelity International scores 100
   against Fidelity Investments and is a different company).
2. ``candidates_for`` — for each new company, ordered candidates:
   ``discovery_overrides.csv`` rows (knowledge- or Chrome-sourced) → generic
   ATS slug probes (Greenhouse/Lever/SmartRecruiters/Workday) → careers-domain
   probes whose HTML is scanned for ATS links.
3. ``verify`` — run the REAL typed fetcher with ``cap=40``; a candidate is
   resolved iff ≥1 posting parses. HTML-lane candidates are verified with
   Playwright only when ``--browser`` is passed (slow) and are otherwise
   reported ``unverified``.
4. ``emit`` — ``output/mnc_discovery_report.md``, ``output/mnc_discovery.json``
   and ``output/mnc_discovery_entries.py`` (paste-ready ``MNC(...)`` literals).

Nothing here writes to the registry; the entries file is reviewed and pasted
by hand so every addition stays a deliberate, git-visible change.
"""
from __future__ import annotations

import asyncio
import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx
import structlog
from rapidfuzz import fuzz

from mnc_careers.ats import FETCHERS, HTML_ONLY, FetchError, detect_ats, parse_target, strip_search_params
from mnc_careers.ats.base import RawPosting
from mnc_careers.registry import MNC, MNC_REGISTRY
from services.scoring import _company_slug
from services.title_filter import is_relevant_title

log = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
INPUT_CSV = DATA_DIR / "mnc_input.csv"
OVERRIDES_CSV = DATA_DIR / "discovery_overrides.csv"

# CSV name -> registry name. The ONLY source of alias truth (fuzzy is advisory).
CSV_ALIASES: dict[str, str] = {
    "EY": "EY (Ernst & Young)",
    "NTT / NTT Data": "NTT Data",
    "Moody's": "Moody's Analytics",
    "Philips": "Philips HealthTech",
    "Boston Consulting Group": "BCG (Boston Consulting Group)",
    "Samsung": "Samsung India R&D",
    "Sony": "Sony India Software Centre",
    "London Stock Exchange Group": "LSEG (Refinitiv)",
}

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}
_WORKDAY_WD = ("wd1", "wd3", "wd5", "wd2", "wd10", "wd12", "wd103", "wd108")

_ATS_LINK_RES = [
    re.compile(r"https?://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[A-Za-z0-9_\-/]*", re.I),
    re.compile(r"https?://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/[A-Za-z0-9_-]+", re.I),
    re.compile(r"https?://jobs(?:\.eu)?\.lever\.co/[A-Za-z0-9_-]+", re.I),
    re.compile(r"https?://(?:jobs|careers)\.smartrecruiters\.com/[A-Za-z0-9_-]+", re.I),
    re.compile(r"https?://[a-z0-9-]+\.eightfold\.ai/careers[^\"'\s<>]*", re.I),
    re.compile(r"https?://[a-z0-9.-]+\.icims\.com/jobs[^\"'\s<>]*", re.I),
    re.compile(r"https?://[a-z0-9.-]+\.taleo\.net/careersection/[^\"'\s<>]*", re.I),
    re.compile(r"https?://[a-z0-9.-]+\.oraclecloud\.com/hcmUI/CandidateExperience/[^\"'\s<>]*", re.I),
    re.compile(r"https?://[a-z0-9.-]+/search/\?q=[^\"'\s<>]*", re.I),  # SuccessFactors
]


# ----------------------------------------------------------------------------
# Data types
# ----------------------------------------------------------------------------

@dataclass
class InputCompany:
    name: str
    hq_country: str


@dataclass
class Candidate:
    url: str
    ats_hint: str = ""
    origin: str = ""  # "override:knowledge" | "override:chrome" | "probe:slug" | "probe:domain" | "probe:html-link"
    delhi_ncr_office: str = ""
    notes: str = ""
    domain: str = ""  # careers domain hint for probe_generic


@dataclass
class Verification:
    ok: bool
    ats: str
    listing_url: str
    api_url: str = ""
    total_reported: Optional[int] = None
    fetched: int = 0
    sample_title: str = ""
    sample_location: str = ""
    pm_titles: int = 0
    error: str = ""
    verified_by: str = ""  # "api" | "browser" | ""


@dataclass
class CompanyResult:
    company: InputCompany
    classification: str  # exact | alias | new
    registry_name: str = ""
    possible_alias: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    tried: list[str] = field(default_factory=list)
    verification: Optional[Verification] = None
    chosen: Optional[Candidate] = None

    @property
    def resolved(self) -> bool:
        return bool(self.verification and self.verification.ok)


# ----------------------------------------------------------------------------
# Input + classification
# ----------------------------------------------------------------------------

def load_input_csv(path: Path = INPUT_CSV) -> list[InputCompany]:
    out: list[InputCompany] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("Company") or row.get("company") or "").strip()
            if not name:
                continue
            country = (row.get("HQ / qualifying parent country") or row.get("hq_country") or "").strip()
            out.append(InputCompany(name=name, hq_country=country))
    return out


def load_overrides(path: Path = OVERRIDES_CSV) -> dict[str, list[Candidate]]:
    """company (lowercased) -> candidates, in file order."""
    if not path.exists():
        return {}
    out: dict[str, list[Candidate]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            company = (row.get("company") or "").strip()
            url = (row.get("candidate_url") or "").strip()
            if not (company and url):
                continue
            out.setdefault(company.lower(), []).append(
                Candidate(
                    url=url,
                    ats_hint=(row.get("ats_hint") or "").strip(),
                    origin=f"override:{(row.get('source') or 'knowledge').strip()}",
                    delhi_ncr_office=(row.get("delhi_ncr_office") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                    domain=(row.get("domain") or "").strip(),
                )
            )
    return out


def name_variants(name: str) -> list[str]:
    """The full cell first, then its alternates: "Teleperformance / TP" → ["Teleperformance / TP", "Teleperformance", "TP"]."""
    parts = [p.strip() for p in re.split(r"\s+/\s+", name) if p.strip()]
    return [name] + [p for p in parts if p != name] if len(parts) > 1 else [name]


def classify_against_registry(
    companies: list[InputCompany], registry: list[MNC] = MNC_REGISTRY
) -> list[CompanyResult]:
    by_slug = {_company_slug(m.name): m.name for m in registry}
    results: list[CompanyResult] = []
    for c in companies:
        res = CompanyResult(company=c, classification="new")
        if c.name in CSV_ALIASES:
            res.classification, res.registry_name = "alias", CSV_ALIASES[c.name]
        else:
            for variant in name_variants(c.name):
                slug = _company_slug(variant)
                if slug in by_slug:
                    res.classification, res.registry_name = "exact", by_slug[slug]
                    break
        if res.classification == "new":
            # advisory only — surfaced in the report, never acted on
            best = max(
                ((fuzz.token_set_ratio(_company_slug(c.name), s), n) for s, n in by_slug.items()),
                default=(0, ""),
            )
            if best[0] >= 90:
                res.possible_alias = f"{best[1]} ({best[0]:.0f})"
        results.append(res)
    return results


# ----------------------------------------------------------------------------
# Candidate generation
# ----------------------------------------------------------------------------

def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slug_variants(name: str) -> list[str]:
    out: list[str] = []
    for variant in name_variants(name):
        base = re.sub(r"\((.*?)\)", " ", _ascii(variant)).lower()
        base = re.sub(r"\b(group|global|international|holdings?|plc|inc|ltd|ag|sa|se|nv|bv|gmbh|corporation|corp|company|co|the|and)\b", " ", base)
        tokens = [t for t in re.sub(r"[^a-z0-9]+", " ", base).split() if t]
        if not tokens:
            continue
        joined = "".join(tokens)
        hyphen = "-".join(tokens)
        # NO first-token variant: "knight" resolved to Knight Gayles, "indigo" to an insurer.
        for s in (joined, hyphen):
            if s and len(s) >= 3 and s not in out:
                out.append(s)
    return out


def domain_guesses(name: str, override_domain: str = "") -> list[str]:
    if override_domain:
        d = override_domain.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
        return [d]
    return [f"{s}.com" for s in slug_variants(name) if "-" not in s][:2]


def scan_html_for_ats_links(html: str, base_url: str = "") -> list[str]:
    found: list[str] = []
    for rx in _ATS_LINK_RES:
        for m in rx.findall(html):
            u = m.rstrip("/\\'\"")
            if u not in found:
                found.append(u)
    # relative careers links to follow one hop
    for m in re.findall(r"href=[\"']([^\"']*(?:careers|jobs|join-us|work-with-us)[^\"']*)[\"']", html, re.I)[:5]:
        u = urljoin(base_url, m) if base_url else m
        if u.startswith("http") and u not in found:
            found.append(u)
    return found[:12]


async def _get(client: httpx.AsyncClient, url: str, *, timeout: float = 15.0, accept: str = "text/html,application/json") -> Optional[httpx.Response]:
    try:
        return await client.get(url, headers={"Accept": accept}, timeout=timeout)
    except Exception:
        return None


async def probe_generic(client: httpx.AsyncClient, name: str, domain_hint: str = "") -> tuple[list[Candidate], list[str]]:
    """Cheap, parallel probes of well-known ATS URL shapes for a company name."""
    tried: list[str] = []
    cands: list[Candidate] = []
    slugs = slug_variants(name)

    async def _try(url: str, check, ats: str, origin: str) -> None:  # noqa: ANN001
        tried.append(url)
        resp = await _get(client, url)
        if resp is None:
            return
        try:
            ok, final_url = check(resp)
        except Exception:
            return
        if ok == "meta":
            # Greenhouse: confirm the board's display name matches the company
            slug = url.split("/v1/boards/")[1].split("/")[0]
            meta = await _get(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}", accept="application/json")
            try:
                ok = meta is not None and meta.status_code == 200 and _plausible(meta.json().get("name", ""))
            except ValueError:
                ok = False
        if ok:
            cands.append(Candidate(url=final_url or url, ats_hint=ats, origin=origin))

    def _plausible(candidate_name: str) -> bool:
        """A probe-derived board must belong to *this* company (slug collisions are common)."""
        if not candidate_name:
            return False
        a, b = _company_slug(name), _company_slug(candidate_name)
        return fuzz.partial_ratio(a, b) >= 80 or fuzz.token_set_ratio(a, b) >= 80

    def _gh(resp: httpx.Response):
        if resp.status_code != 200 or "jobs" not in resp.text[:200]:
            return False, ""
        # board name lives at /v1/boards/{slug}; the jobs URL tells us the slug
        return "meta", ""  # verified after the fact in _gh_board_ok

    def _lever(resp: httpx.Response):
        return resp.status_code == 200 and resp.text.lstrip().startswith("["), ""

    def _sr(resp: httpx.Response):
        if resp.status_code != 200 or '"totalFound"' not in resp.text[:500]:
            return False, ""
        try:
            content = resp.json().get("content") or []
        except ValueError:
            return False, ""
        company = ""
        if content:
            c = content[0].get("company")
            company = c.get("name", "") if isinstance(c, dict) else str(c or "")
        return _plausible(company), ""

    def _wd(resp: httpx.Response):
        final = str(resp.url)
        segs = [s for s in urlsplit(final).path.split("/") if s]
        return (resp.status_code == 200 and "myworkdayjobs.com" in final and bool(segs) and "wday" not in segs), final

    tasks = []
    for s in slugs[:3]:
        tasks.append(_try(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=false", _gh, "greenhouse", "probe:slug"))
        tasks.append(_try(f"https://api.lever.co/v0/postings/{s}?mode=json", _lever, "lever", "probe:slug"))
        tasks.append(_try(f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1", _sr, "smartrecruiters", "probe:slug"))
        if "-" not in s:
            for wd in _WORKDAY_WD[:5]:
                tasks.append(_try(f"https://{s}.{wd}.myworkdayjobs.com/", _wd, "workday", "probe:slug"))
    await asyncio.gather(*tasks)

    # careers-domain probes → scan HTML for ATS links
    for d in domain_guesses(name, domain_hint):
        for url in (f"https://careers.{d}", f"https://jobs.{d}", f"https://www.{d}/careers", f"https://{d}/careers", f"https://www.{d}/en/careers"):
            tried.append(url)
            resp = await _get(client, url)
            if resp is None or resp.status_code >= 400:
                continue
            final = str(resp.url)
            ats = detect_ats(final)
            if ats:
                cands.append(Candidate(url=final, ats_hint=ats, origin="probe:domain"))
            for link in scan_html_for_ats_links(resp.text, final):
                if detect_ats(link) and all(c.url != link for c in cands):
                    cands.append(Candidate(url=link, ats_hint=detect_ats(link), origin="probe:html-link"))
            if any(c.origin.startswith("probe:") and c.ats_hint for c in cands):
                break
    # de-dup by URL keeping order
    seen: set[str] = set()
    uniq = []
    for c in cands:
        if c.url not in seen:
            seen.add(c.url)
            uniq.append(c)
    return uniq, tried


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------

def _mnc_for(name: str, cand: Candidate) -> MNC:
    ats = cand.ats_hint or detect_ats(cand.url)
    api_url = ""
    listing = cand.url
    if ats in ("greenhouse", "lever") and ("api." in urlsplit(cand.url).netloc or "boards-api." in urlsplit(cand.url).netloc):
        api_url = cand.url
    return MNC(name, cand.url, cand.delhi_ncr_office, listing, cand.notes, api_url, ats if ats in FETCHERS or ats == "html" else "")


async def verify_api(client: httpx.AsyncClient, name: str, cand: Candidate, *, log: Any = log) -> Verification:
    mnc = _mnc_for(name, cand)
    ats = mnc.ats_type
    if ats not in FETCHERS:
        return Verification(False, ats or "html", cand.url, error="no typed fetcher (needs --browser or override ats_hint)")
    try:
        fr = await asyncio.wait_for(
            FETCHERS[ats](mnc, client, cap=40, net_keywords=[], title_predicate=is_relevant_title,
                          host_sem=asyncio.Semaphore(2), log=log.bind(company=name)),
            timeout=60,
        )
    except asyncio.TimeoutError:
        return Verification(False, ats, cand.url, error="timeout")
    except FetchError as exc:
        return Verification(False, ats, cand.url, error=str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        return Verification(False, ats, cand.url, error=f"{type(exc).__name__}: {exc}"[:200])
    postings: list[RawPosting] = fr.postings
    if not postings:
        return Verification(False, ats, cand.url, total_reported=fr.total_reported, error="0 postings parsed")
    api_url = mnc.api_url
    if ats == "workday":
        t = parse_target(cand.url, "workday")
        listing = f"https://{t['host']}/{t['site']}"
    elif ats == "greenhouse":
        board = parse_target(cand.url, "greenhouse")["board"]
        listing = f"https://boards.greenhouse.io/{board}"
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    elif ats == "lever":
        slug = parse_target(cand.url, "lever")["slug"]
        listing = f"https://jobs.lever.co/{slug}"
        api_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    elif ats == "smartrecruiters":
        listing = f"https://jobs.smartrecruiters.com/{parse_target(cand.url, 'smartrecruiters')['company']}"
    elif ats == "successfactors":
        listing = parse_target(cand.url, "successfactors")["base"]
    else:
        listing = strip_search_params(cand.url)
    return Verification(
        True, ats, listing,
        api_url=api_url, total_reported=fr.total_reported, fetched=len(postings),
        sample_title=postings[0].title, sample_location=postings[0].location,
        pm_titles=sum(1 for p in postings if is_relevant_title(p.title)), verified_by="api",
    )


async def verify_browser(bm: Any, settings: Any, name: str, cand: Candidate, *, log: Any = log) -> Verification:
    from mnc_careers import html_generic

    mnc = _mnc_for(name, cand)
    try:
        fr = await asyncio.wait_for(
            html_generic.fetch_all(mnc, bm, cookies_dir=settings.COOKIES_DIR, max_pages=1,
                                   listing_url=strip_search_params(cand.url), net_url=cand.url, log=log.bind(company=name)),
            timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        return Verification(False, "html", cand.url, error=f"{type(exc).__name__}: {exc}"[:200])
    if not fr.postings:
        return Verification(False, "html", cand.url, error="0 postings parsed (browser)")
    # Marketing pages contain <article>/<a> noise that parse_cards picks up. Accept only
    # when the page's own JSON API answered, or ≥3 card links really look like job URLs.
    jobish = [p for p in fr.postings if html_generic.looks_like_job_url(p.url)]
    if fr.json_postings == 0 and len(jobish) < 3:
        return Verification(False, "html", cand.url, fetched=len(fr.postings),
                            error=f"browser parsed {len(fr.postings)} elements but only {len(jobish)} look like job links — not a listing page")
    best = jobish or fr.postings
    return Verification(
        True, cand.ats_hint or detect_ats(cand.url) or "html", strip_search_params(cand.url),
        fetched=len(fr.postings), sample_title=best[0].title, sample_location=best[0].location,
        pm_titles=sum(1 for p in fr.postings if is_relevant_title(p.title)), verified_by="browser",
    )


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------

async def run_discovery(
    *,
    input_csv: Path = INPUT_CSV,
    overrides_csv: Path = OVERRIDES_CSV,
    only: Optional[list[str]] = None,
    dry_run: bool = False,
    use_browser: bool = False,
    concurrency: int = 8,
    settings: Any = None,
    log: Any = log,
) -> list[CompanyResult]:
    companies = load_input_csv(input_csv)
    results = classify_against_registry(companies)
    overrides = load_overrides(overrides_csv)

    if only:
        wanted = {_company_slug(o) for o in only}
        lowered = [o.lower() for o in only]
        results = [r for r in results if _company_slug(r.company.name) in wanted or any(o in r.company.name.lower() for o in lowered)]
        todo = results
    else:
        todo = [r for r in results if r.classification == "new"]

    for r in todo:
        r.candidates = list(overrides.get(r.company.name.lower(), []))
    if dry_run:
        return results

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency * 3)
    bm = None
    if use_browser:
        from browser.context import BrowserManager

        bm = BrowserManager()
        await bm.start()
    try:
        async with httpx.AsyncClient(headers=_UA, follow_redirects=True, timeout=20, limits=limits) as client:

            async def _one(r: CompanyResult) -> None:
                async with sem:
                    domain_hint = next((c.domain for c in r.candidates if c.domain), "")
                    probed, tried = await probe_generic(client, r.company.name, domain_hint)
                    r.tried.extend(tried)
                    for c in probed:
                        if all(c.url != x.url for x in r.candidates):
                            r.candidates.append(c)
                    unverified: Optional[tuple[Candidate, Verification]] = None
                    for cand in r.candidates:
                        ats = cand.ats_hint or detect_ats(cand.url)
                        if ats in FETCHERS:
                            v = await verify_api(client, r.company.name, cand, log=log)
                            # A board found by slug-guessing must look like an MNC board: name
                            # collisions ("Indigo" the insurer vs IndiGo) are the failure mode.
                            if v.ok and cand.origin == "probe:slug" and (v.total_reported or 0) < 10:
                                v = Verification(False, v.ats, cand.url, total_reported=v.total_reported,
                                                 error=f"probe:slug board too small ({v.total_reported}) — likely a different company")
                        elif bm is not None:
                            v = await verify_browser(bm, settings, r.company.name, cand, log=log)
                        else:
                            v = Verification(False, ats or "html", cand.url, error="unverified: HTML lane (re-run with --browser)")
                            if unverified is None:
                                unverified = (cand, v)
                        r.verification = v
                        r.chosen = cand
                        if v.ok:
                            break
                    if not r.resolved and unverified is not None:
                        # prefer reporting the hand-provided HTML candidate over a rejected probe
                        r.chosen, r.verification = unverified
                    log.info("discover.company", company=r.company.name, resolved=r.resolved,
                             candidates=len(r.candidates), error=(r.verification.error if r.verification else "no candidates"))

            await asyncio.gather(*(_one(r) for r in todo))
    finally:
        if bm is not None:
            await bm.stop()
    return results


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------

def _py_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def entry_literal(r: CompanyResult) -> str:
    assert r.chosen and r.verification and r.verification.ok
    v, c = r.verification, r.chosen
    lines = [
        "    MNC(",
        f"        name={_py_str(r.company.name)},",
        f"        careers_url={_py_str(c.url)},",
        f"        delhi_ncr_office={_py_str(c.delhi_ncr_office)},",
        f"        pm_search_url={_py_str(v.listing_url)},",
    ]
    if v.api_url:
        lines.append(f"        api_url={_py_str(v.api_url)},")
    # only pin api_type when detection cannot derive it (custom domains, html force)
    if v.ats and detect_ats(v.api_url or v.listing_url) != v.ats:
        lines.append(f"        api_type={_py_str(v.ats)},")
    note = f"discovered {date.today().isoformat()} via {c.origin}; total={v.total_reported if v.total_reported is not None else '?'}"
    if c.notes:
        note = f"{c.notes}; {note}"
    lines.append(f"        notes={_py_str(note)},")
    lines.append(f"        hq_country={_py_str(r.company.hq_country)},")
    lines.append("    ),")
    return "\n".join(lines)


def emit(results: list[CompanyResult], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    new = [r for r in results if r.classification == "new"]
    resolved = [r for r in new if r.resolved]
    unresolved = [r for r in new if not r.resolved]
    exact = [r for r in results if r.classification == "exact"]
    alias = [r for r in results if r.classification == "alias"]

    md = [f"# MNC discovery report — {date.today().isoformat()}", ""]
    md.append(f"- input companies: **{len(results)}** — exact {len(exact)} · alias {len(alias)} · new {len(new)}")
    md.append(f"- new resolved: **{len(resolved)}** · unresolved: **{len(unresolved)}**")
    md += ["", "## Resolved (new entries)", "", "| company | HQ | ATS | listing URL | total | sample title | sample location | PM titles | via |", "|---|---|---|---|---|---|---|---|---|"]
    for r in resolved:
        v = r.verification
        assert v and r.chosen
        md.append(f"| {r.company.name} | {r.company.hq_country} | {v.ats} | {v.listing_url} | {v.total_reported if v.total_reported is not None else '?'} | {v.sample_title[:50]} | {v.sample_location[:40]} | {v.pm_titles} | {r.chosen.origin} |")
    md += ["", "## Unresolved (need Chrome / manual override)", "", "| company | HQ | possible alias | candidates tried | last error |", "|---|---|---|---|---|"]
    for r in unresolved:
        err = r.verification.error if r.verification else "no candidates found"
        md.append(f"| {r.company.name} | {r.company.hq_country} | {r.possible_alias} | {len(r.candidates)} cand / {len(r.tried)} probes | {err[:90]} |")
    md += ["", "## Already in registry", "", "| CSV name | registry name | how |", "|---|---|---|"]
    for r in exact + alias:
        md.append(f"| {r.company.name} | {r.registry_name} | {r.classification} |")
    md += ["", "## Unresolved — URLs tried", ""]
    for r in unresolved:
        md.append(f"### {r.company.name}")
        for c in r.candidates:
            md.append(f"- candidate `{c.url}` ({c.ats_hint or '?'}, {c.origin})")
        for t in r.tried[:20]:
            md.append(f"- probe `{t}`")
        md.append("")
    report = out_dir / "mnc_discovery_report.md"
    report.write_text("\n".join(md), encoding="utf-8")

    js = out_dir / "mnc_discovery.json"
    js.write_text(json.dumps([
        {
            "company": asdict(r.company), "classification": r.classification, "registry_name": r.registry_name,
            "possible_alias": r.possible_alias, "resolved": r.resolved,
            "chosen": asdict(r.chosen) if r.chosen else None,
            "verification": asdict(r.verification) if r.verification else None,
            "candidates": [asdict(c) for c in r.candidates], "tried": r.tried,
        }
        for r in results
    ], indent=2, ensure_ascii=False), encoding="utf-8")

    entries = out_dir / "mnc_discovery_entries.py"
    body = ["# Paste-ready MNC(...) literals — review, then append to mnc_careers/registry.py", ""]
    by_country: dict[str, list[CompanyResult]] = {}
    for r in resolved:
        by_country.setdefault(r.company.hq_country or "Unknown", []).append(r)
    for country in sorted(by_country):
        body.append(f"    # ---- Discovered: {country} ----")
        body += [entry_literal(r) for r in by_country[country]]
    entries.write_text("\n".join(body) + "\n", encoding="utf-8")
    return {"report": report, "json": js, "entries": entries}


# ----------------------------------------------------------------------------
# Repair mode — re-verify EXISTING registry entries and propose URL patches
# ----------------------------------------------------------------------------

_WD_HOSTS = ("wd1", "wd3", "wd5", "wd10", "wd12", "wd101", "wd102", "wd103", "wd104", "wd105", "wd108")
_WD_COMMON_SITES = ("External", "Careers", "External_Careers", "careers", "external", "ExternalCareers", "jobs-and-careers")


@dataclass
class RepairResult:
    name: str
    old_url: str
    ats: str
    status: str  # "ok" | "repaired" | "fallback_html" | "unresolved"
    new_url: str = ""
    new_api_type: str = ""
    total_reported: Optional[int] = None
    sample_title: str = ""
    error: str = ""
    tried: int = 0
    researched: bool = False  # fallback came from discovery_overrides.csv, not the marketing careers_url


async def workday_variants(client: httpx.AsyncClient, url: str, extra_sites: list[str], *, tried: list[str]) -> Optional[tuple[str, int]]:
    """Try the CXS endpoint across data-center hosts × site names. Returns (listing_url, total)."""
    t = parse_target(url, "workday")
    tenant, site0 = t["tenant"], t["site"]
    sites = list(dict.fromkeys([s for s in [site0, *extra_sites, *_WD_COMMON_SITES] if s]))
    hosts = list(dict.fromkeys([t["host"], *(f"{tenant}.{wd}.myworkdayjobs.com" for wd in _WD_HOSTS)]))
    sem = asyncio.Semaphore(6)
    body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    hdrs = {"Accept": "application/json", "Content-Type": "application/json"}

    async def _try(host: str, site: str) -> Optional[tuple[str, int]]:
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        tried.append(api)
        async with sem:
            try:
                r = await client.post(api, json=body, headers=hdrs, timeout=15)
            except Exception:
                return None
        if r.status_code != 200:
            return None
        try:
            total = r.json().get("total")
        except ValueError:
            return None
        if isinstance(total, int) and total > 0:
            return f"https://{host}/{site}", total
        return None

    # original host × its own site first (cheap), then the full host × site sweep
    hit = await _try(hosts[0], sites[0])
    if hit:
        return hit
    results = await asyncio.gather(*(_try(h, s) for h in hosts for s in sites if not (h == hosts[0] and s == sites[0])))
    hits = [r for r in results if r]
    # prefer the original host when several data centers answer
    hits.sort(key=lambda r: (not r[0].startswith(f"https://{hosts[0]}/"), -r[1]))
    return hits[0] if hits else None


async def repair_entry(client: httpx.AsyncClient, mnc: MNC, *, overrides: Optional[dict[str, list[Candidate]]] = None, log: Any = log) -> RepairResult:
    url = mnc.api_url or mnc.pm_search_url
    ats = mnc.ats_type
    res = RepairResult(mnc.name, url, ats or "html", "unresolved")
    tried: list[str] = []
    override_cands = list((overrides or {}).get(mnc.name.lower(), []))

    # 0) hand-researched candidates (discovery_overrides.csv) win over everything
    for cand in override_cands:
        a = cand.ats_hint or detect_ats(cand.url)
        if a not in FETCHERS:
            continue
        v = await verify_api(client, mnc.name, cand, log=log)
        tried.append(cand.url)
        if v.ok and v.listing_url != url:
            res.status, res.new_url = "repaired", v.listing_url
            res.new_api_type = "" if detect_ats(v.listing_url) == v.ats else v.ats
            res.total_reported, res.sample_title, res.ats = v.total_reported, v.sample_title, v.ats
            res.tried = len(tried)
            return res
        if v.ok:
            res.status, res.total_reported, res.sample_title = "ok", v.total_reported, v.sample_title
            return res

    # 1) does the current entry work?
    if ats in FETCHERS:
        v = await verify_api(client, mnc.name, Candidate(url=url, ats_hint=ats), log=log)
        if v.ok:
            res.status, res.total_reported, res.sample_title = "ok", v.total_reported, v.sample_title
            return res
        res.error = v.error
    else:
        # HTML lane entries are not verified without a browser; but a hand-researched
        # override pointing elsewhere is a fix we can propose right away.
        html_override = next((c for c in override_cands if (c.ats_hint or detect_ats(c.url)) not in FETCHERS and c.url != url), None)
        if html_override:
            hinted = html_override.ats_hint or detect_ats(html_override.url)
            res.status, res.new_url, res.researched = "fallback_html", html_override.url, True
            res.new_api_type = hinted if hinted in HTML_ONLY and detect_ats(html_override.url) != hinted else ("" if detect_ats(html_override.url) else "html")
            res.ats = hinted or "html"
            return res
        res.status = "ok"
        res.error = "html lane — not verified without --browser"
        return res

    # 2) scan the company's careers page for ATS links
    extra_sites: list[str] = []
    cands: list[Candidate] = []
    if mnc.careers_url:
        tried.append(mnc.careers_url)
        resp = await _get(client, mnc.careers_url)
        if resp is not None and resp.status_code < 400:
            final = str(resp.url)
            for link in [final, *scan_html_for_ats_links(resp.text, final)]:
                a = detect_ats(link)
                if a and all(c.url != link for c in cands):
                    cands.append(Candidate(url=link, ats_hint=a, origin="repair:careers-page"))
                if a == "workday":
                    site = parse_target(link, "workday")["site"]
                    if site:
                        extra_sites.append(site)

    # 3) Workday: host × site variants (tenants migrate data centers, sites get renamed)
    if ats == "workday":
        hit = await workday_variants(client, url, extra_sites, tried=tried)
        if hit:
            cands.insert(0, Candidate(url=hit[0], ats_hint="workday", origin="repair:workday-variants"))

    for cand in cands:
        a = cand.ats_hint or detect_ats(cand.url)
        if a not in FETCHERS:
            continue
        v = await verify_api(client, mnc.name, cand, log=log)
        tried.append(cand.url)
        if v.ok:
            res.status, res.new_url, res.new_api_type = "repaired", v.listing_url, ("" if detect_ats(v.listing_url) == v.ats else v.ats)
            res.total_reported, res.sample_title, res.ats = v.total_reported, v.sample_title, v.ats
            res.tried = len(tried)
            return res
        res.error = v.error

    # 4) fall back: a hand-researched HTML-lane override (any non-typed ATS: html, eightfold,
    #    oracle_hcm, icims, ...), else the careers page itself, in the HTML lane
    html_override = next((c for c in override_cands if (c.ats_hint or detect_ats(c.url)) not in FETCHERS), None)
    fallback = html_override.url if html_override else mnc.careers_url
    if fallback:
        hinted = (html_override.ats_hint or detect_ats(html_override.url)) if html_override else ""
        res.status, res.new_url = "fallback_html", fallback
        # keep a recognised HTML-lane ATS label (oracle_hcm, eightfold, …) when we know it
        res.new_api_type = hinted if hinted and hinted in HTML_ONLY and detect_ats(fallback) != hinted else ("" if detect_ats(fallback) else "html")
        res.ats = hinted or "html"
        res.researched = html_override is not None
    res.tried = len(tried)
    return res


async def run_repair(*, only: Optional[list[str]] = None, ats: Optional[str] = None, concurrency: int = 6, log: Any = log) -> list[RepairResult]:
    from mnc_careers.scraper import select_targets

    targets = select_targets(MNC_REGISTRY, only=only, ats=ats, aliases=CSV_ALIASES)
    overrides = load_overrides()
    sem = asyncio.Semaphore(concurrency)
    out: list[RepairResult] = []
    async with httpx.AsyncClient(headers=_UA, follow_redirects=True, timeout=20, limits=httpx.Limits(max_connections=concurrency * 4)) as client:

        async def _one(m: MNC) -> None:
            async with sem:
                r = await repair_entry(client, m, overrides=overrides, log=log)
                out.append(r)
                log.info("repair.entry", company=m.name, status=r.status, new_url=r.new_url or "", error=r.error[:80])

        await asyncio.gather(*(_one(m) for m in targets))
    order = {m.name: i for i, m in enumerate(targets)}
    out.sort(key=lambda r: order.get(r.name, 1 << 30))
    return out


def apply_repairs(results: list[RepairResult], registry_path: Path, *, include_fallback: bool = False) -> int:
    """Rewrite pm_search_url (and add api_type) in registry.py for repaired entries.

    ``fallback_html`` proposals (the company's marketing careers page) are only
    applied with ``include_fallback=True`` — they are usually a worse listing
    than a dead URL and belong in the discovery queue instead.

    Textual, URL-anchored edits: the old URL string is unique per entry, so we
    replace it in place and, when an api_type override is needed, insert it
    before the entry's closing ``    ),``. Returns the number of entries changed.
    """
    src = registry_path.read_text(encoding="utf-8")
    changed = 0
    for r in results:
        if not r.new_url:
            continue
        if r.status == "repaired":
            pass
        elif r.status == "fallback_html" and include_fallback and r.researched:
            pass  # hand-researched HTML-lane URL from discovery_overrides.csv
        else:
            continue
        old_lit = json.dumps(r.old_url, ensure_ascii=False)
        if old_lit not in src:
            old_lit = f'"{r.old_url}"'
            if old_lit not in src:
                continue
        new_lit = json.dumps(r.new_url, ensure_ascii=False)
        # Discovered entries carry the same URL in careers_url AND pm_search_url; the
        # listing URL is the one that must change, so anchor on the keyword form
        # first and only then fall back to the first (positional) occurrence.
        kw = f"pm_search_url={old_lit}"
        idx = src.index(kw) + len("pm_search_url=") if kw in src else src.index(old_lit)
        src = src[:idx] + new_lit + src[idx + len(old_lit):]
        if r.new_api_type:
            end = src.index("\n    ),", idx)
            block = src[idx:end]
            if "api_type=" in block:
                block = re.sub(r'api_type="[^"]*"', f'api_type="{r.new_api_type}"', block)
                src = src[:idx] + block + src[end:]
            else:
                src = src[:end] + f'\n        api_type="{r.new_api_type}",' + src[end:]
        elif r.status == "repaired":
            # a working typed URL: drop a stale api_type="html" if present in this entry
            end = src.index("\n    ),", idx)
            block = src[idx:end].replace('\n        api_type="html",', "")
            src = src[:idx] + block + src[end:]
        changed += 1
    registry_path.write_text(src, encoding="utf-8")
    return changed


def emit_repair(results: list[RepairResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"# MNC registry repair — {date.today().isoformat()}", ""]
    counts = {s: sum(r.status == s for r in results) for s in ("ok", "repaired", "fallback_html", "unresolved")}
    md.append("- " + " · ".join(f"{k}: **{v}**" for k, v in counts.items()))
    md += ["", "| company | status | ATS | old URL | new URL | total | sample | error |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.status == "ok":
            continue
        md.append(f"| {r.name} | {r.status} | {r.ats} | {r.old_url[:60]} | {r.new_url[:70]} | {r.total_reported if r.total_reported is not None else ''} | {r.sample_title[:40]} | {r.error[:60]} |")
    path = out_dir / "mnc_repair_report.md"
    path.write_text("\n".join(md), encoding="utf-8")
    (out_dir / "mnc_repair.json").write_text(json.dumps([asdict(r) for r in results], indent=1, ensure_ascii=False), encoding="utf-8")
    return path
