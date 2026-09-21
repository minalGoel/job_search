"""Structured job detail behind a listing: the per-job record an ATS exposes once you
follow the posting URL — real office addresses, the declared workplace type, the full
description.

Listings are coarse ("India (Hybrid)", "3 Locations", "Remote") and our location gate,
work-mode heuristics and scoring all ran on that string. The detail record is where the
truth is (see docs/known_edge_cases.md §36). Strategies, picked from the URL:

* Oracle HCM  — ``recruitingCEJobRequisitionDetails`` (finder ``ById;Id="…",siteNumber=…``)
* Workday     — CXS ``/wday/cxs/{tenant}/{site}{externalPath}`` (same call the Workday
                fetcher makes for "N Locations"; parsed by :func:`parse_workday_detail`)
* SmartRecruiters — ``api.smartrecruiters.com/v1/companies/{co}/postings/{id}``
* Greenhouse  — ``boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}``
* everything else — GET the page and read schema.org **JobPosting** JSON-LD, falling back
  to schema.org **microdata** (SuccessFactors classic, SmartRecruiters pages).

Every strategy returns the same :class:`DetailRecord`; the resolver
(services/location_resolver.py) turns it into a location verdict. Nothing here decides
anything — it only reads.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from mnc_careers.ats.base import FetchError, looks_like_challenge, request, request_json
from mnc_careers.ats.detect import parse_target
from services.location_filter import canonical_city

_INDIA_COUNTRY = {"in", "ind", "india", "republic of india"}


def strip_html(text: str) -> str:
    """Tags → spaces, entities decoded, whitespace collapsed. Local copy so this module
    never imports the scrapers package (which pulls Playwright into uvicorn)."""
    if not text:
        return ""
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


_REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")
_HYBRID_WORDS = ("hybrid", "flexible")


@dataclass
class DetailLocation:
    city: str = ""
    region: str = ""
    country: str = ""       # as written ('IN', 'India', 'Philippines'); use is_india() to compare
    postal: str = ""
    raw: str = ""           # the string the source gave, untouched

    def is_india(self) -> Optional[bool]:
        c = (self.country or "").strip().lower()
        if not c:
            return None
        return c in _INDIA_COUNTRY

    def display(self) -> str:
        parts = [self.city, self.region, self.country]
        out = ", ".join(p for p in parts if p)
        return out or self.raw


@dataclass
class DetailRecord:
    source: str = ""                 # oracle_api | workday_cxs | smartrecruiters_api | greenhouse_api | sf_unify | jsonld | microdata
    status: str = "none"             # ok | none | blocked | error
    url: str = ""
    locations: list[DetailLocation] = field(default_factory=list)
    workplace_type: str = ""         # remote | hybrid | onsite | remote_or_hybrid | ''
    description: str = ""
    posted_date: str = ""
    employment_type: str = ""
    error: str = ""

    def city_level(self) -> list[DetailLocation]:
        return [l for l in self.locations if l.city]

    def to_row(self) -> dict:
        """Columns for job_enrichment (the structured half)."""
        return {
            "en_detail_source": self.source,
            "en_detail_url": self.url,
            "en_detail_status": self.status,
            "en_locations_json": [asdict(l) for l in self.locations],
            "en_workplace_type": self.workplace_type,
            "en_description_full": self.description[:20000],
            "en_posted_date": self.posted_date,
            "en_employment_type": self.employment_type,
        }


# ── helpers ───────────────────────────────────────────────────────────────────

_PSEUDO_PLACES = {"anywhere", "remote", "worldwide", "global", "everywhere", "n/a", "na", "none", "-", "virtual", "home"}


def _clean(s: Any) -> str:
    if s is None:
        return ""
    if isinstance(s, dict):
        s = s.get("name") or s.get("@value") or ""
    out = re.sub(r"\s+", " ", str(s)).strip()
    # RemoteOK-style JSON-LD fills city/region/country with "Anywhere": that is not a place
    return "" if out.lower() in _PSEUDO_PLACES else out


def _workplace_from_text(*texts: str) -> str:
    blob = " ".join(t.lower() for t in texts if t)
    if any(w in blob for w in _HYBRID_WORDS):
        return "hybrid"
    if any(w in blob for w in _REMOTE_WORDS):
        return "remote"
    return ""


def _split_locality(locality: str) -> DetailLocation:
    """JSON-LD addressLocality is often a whole line: 'Bangalore, Karnataka, India' or an
    office code like 'IND-Gurgaon (SVG)'. Pull a city out of it when we can."""
    raw = _clean(locality)
    if not raw:
        return DetailLocation()
    parts = [p.strip() for p in re.split(r"[,;/]", raw) if p.strip()]
    city = parts[0] if parts else raw
    # office codes: 'IND-Gurgaon (SVG)', 'India-Gurgaon (DLF CyberHub)', 'IND-HR Gurugram', 'NOIDA 05'
    m = re.search(r"(?:^|[-\s])(gurgaon|gurugram|noida|greater noida|new delhi|delhi|faridabad|ghaziabad|bangalore|bengaluru|mumbai|pune|hyderabad|chennai|kolkata)\b", raw, re.I)
    if m:
        city = m.group(1)
    return DetailLocation(city=city, region=parts[1] if len(parts) > 2 else "", country=parts[-1] if len(parts) > 2 else "", raw=raw)


# ── parsers (pure) ────────────────────────────────────────────────────────────

def parse_jsonld(html: str) -> Optional[DetailRecord]:
    """schema.org JobPosting from <script type="application/ld+json"> blocks."""
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for d in candidates:
            if isinstance(d, dict) and "@graph" in d:
                candidates.extend(x for x in d["@graph"] if isinstance(x, dict))
        for d in candidates:
            if not isinstance(d, dict) or "JobPosting" not in str(d.get("@type", "")):
                continue
            rec = DetailRecord(source="jsonld", status="ok")
            jl = d.get("jobLocation") or []
            for place in (jl if isinstance(jl, list) else [jl]):
                if not isinstance(place, dict):
                    continue
                addr = place.get("address") or {}
                if isinstance(addr, str):
                    rec.locations.append(_split_locality(addr))
                    continue
                if not isinstance(addr, dict):
                    continue
                loc = _split_locality(addr.get("addressLocality") or "")
                loc.region = _clean(addr.get("addressRegion")) or loc.region
                loc.country = _clean(addr.get("addressCountry")) or loc.country
                loc.postal = _clean(addr.get("postalCode"))
                loc.raw = ", ".join(p for p in (_clean(addr.get("streetAddress")), _clean(addr.get("addressLocality")),
                                                _clean(addr.get("addressRegion")), _clean(addr.get("postalCode")),
                                                _clean(addr.get("addressCountry"))) if p)
                if loc.city or loc.region or loc.country:
                    rec.locations.append(loc)
            if "TELECOMMUTE" in str(d.get("jobLocationType", "")).upper():
                rec.workplace_type = "remote_or_hybrid"
            rec.description = strip_html(d.get("description") or "")[:20000]
            rec.posted_date = _clean(d.get("datePosted"))[:10]
            et = d.get("employmentType")
            rec.employment_type = ", ".join(et) if isinstance(et, list) else _clean(et)
            if not rec.workplace_type:
                rec.workplace_type = _workplace_from_text(rec.description[:1500])
            return rec
    return None


def parse_microdata(html: str) -> Optional[DetailRecord]:
    """schema.org microdata (itemprop=jobLocation/address) — SuccessFactors classic, SmartRecruiters pages."""
    soup = BeautifulSoup(html, "html.parser")
    posting = soup.select_one('[itemtype*="JobPosting"]') or soup
    addresses = posting.select('[itemprop="jobLocation"] [itemprop="address"], [itemprop="jobLocation"][itemtype*="PostalAddress"], [itemtype*="PostalAddress"]')
    if not addresses:
        return None
    rec = DetailRecord(source="microdata", status="ok")
    for a in addresses:
        def prop(name: str) -> str:
            el = a.select_one(f'[itemprop="{name}"]')
            return _clean(el.get("content") or el.get_text(" ", strip=True)) if el else ""
        loc = _split_locality(prop("addressLocality"))
        loc.region = prop("addressRegion") or loc.region
        loc.country = prop("addressCountry") or loc.country
        loc.postal = prop("postalCode")
        loc.raw = ", ".join(p for p in (prop("streetAddress"), prop("addressLocality"), prop("addressRegion"), prop("postalCode"), prop("addressCountry")) if p)
        if loc.city or loc.region or loc.country:
            rec.locations.append(loc)
    if not rec.locations:
        return None
    desc = posting.select_one('[itemprop="description"]')
    rec.description = strip_html(str(desc))[:20000] if desc else ""
    dp = posting.select_one('[itemprop="datePosted"]')
    rec.posted_date = _clean(dp.get("content") or dp.get_text(strip=True))[:10] if dp else ""
    jlt = posting.select_one('[itemprop="jobLocationType"]')
    if jlt and "TELECOMMUTE" in (jlt.get("content") or jlt.get_text()).upper():
        rec.workplace_type = "remote_or_hybrid"
    if not rec.workplace_type:
        rec.workplace_type = _workplace_from_text(rec.description[:1500])
    return rec


def parse_oracle_detail(data: dict) -> Optional[DetailRecord]:
    items = data.get("items") or []
    if not items:
        return None
    d = items[0]
    rec = DetailRecord(source="oracle_api", status="ok")
    for wl in d.get("workLocation") or []:
        if not isinstance(wl, dict):
            continue
        rec.locations.append(DetailLocation(
            city=_clean(wl.get("TownOrCity")), region=_clean(wl.get("Region2") or wl.get("Region1")),
            country=_clean(wl.get("Country")), postal=_clean(wl.get("PostalCode")),
            raw=", ".join(p for p in (_clean(wl.get("AddressLine1")), _clean(wl.get("TownOrCity")), _clean(wl.get("Region2")),
                                      _clean(wl.get("PostalCode")), _clean(wl.get("Country"))) if p),
        ))
    if not rec.locations and d.get("PrimaryLocation"):
        rec.locations.append(DetailLocation(country=_clean(d.get("PrimaryLocationCountry")), raw=_clean(d.get("PrimaryLocation"))))
    wp = _clean(d.get("WorkplaceType")).lower()
    rec.workplace_type = wp if wp in ("remote", "hybrid", "onsite") else ("onsite" if wp in ("on-site", "on site") else "")
    rec.description = strip_html(" ".join(d.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))[:20000]
    rec.posted_date = _clean(d.get("PostedDate"))[:10]
    return rec


def parse_workday_detail(data: dict) -> Optional[DetailRecord]:
    info = data.get("jobPostingInfo") or {}
    if not info:
        return None
    rec = DetailRecord(source="workday_cxs", status="ok")
    for l in [info.get("location") or ""] + list(info.get("additionalLocations") or []):
        if l:
            rec.locations.append(_split_locality(l))
    remote = _clean(info.get("remoteType")).lower()
    rec.workplace_type = "remote" if "remote" in remote else ("hybrid" if "hybrid" in remote else "")
    rec.description = strip_html(info.get("jobDescription") or "")[:20000]
    rec.posted_date = _clean(info.get("startDate"))[:10]
    rec.employment_type = _clean(info.get("timeType"))
    if not rec.workplace_type:
        rec.workplace_type = _workplace_from_text(rec.description[:1500])
    return rec


def parse_smartrecruiters_posting(data: dict) -> Optional[DetailRecord]:
    loc = data.get("location") or {}
    rec = DetailRecord(source="smartrecruiters_api", status="ok")
    if loc:
        rec.locations.append(DetailLocation(city=_clean(loc.get("city")), region=_clean(loc.get("region")),
                                            country=_clean(loc.get("country")), postal=_clean(loc.get("postalCode")),
                                            raw=_clean(loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p))))
        if loc.get("remote"):
            rec.workplace_type = "remote"
    sections = ((data.get("jobAd") or {}).get("sections") or {})
    rec.description = strip_html(" ".join((s or {}).get("text") or "" for s in sections.values() if isinstance(s, dict)))[:20000]
    rec.posted_date = _clean(data.get("releasedDate"))[:10]
    rec.employment_type = _clean((data.get("typeOfEmployment") or {}).get("label"))
    if not rec.workplace_type:
        rec.workplace_type = _workplace_from_text(rec.description[:1500])
    return rec if (rec.locations or rec.description) else None


def parse_greenhouse_job(data: dict) -> Optional[DetailRecord]:
    rec = DetailRecord(source="greenhouse_api", status="ok")
    name = _clean((data.get("location") or {}).get("name"))
    if name:
        rec.locations.append(_split_locality(name))
    for off in data.get("offices") or []:
        loc = _split_locality(_clean(off.get("location") or off.get("name")))
        if loc.city and all(loc.city.lower() != x.city.lower() for x in rec.locations):
            rec.locations.append(loc)
    rec.description = strip_html(data.get("content") or "")[:20000]
    rec.posted_date = _clean(data.get("updated_at"))[:10]
    if "remote" in name.lower():
        rec.workplace_type = "remote"
    if not rec.workplace_type:
        rec.workplace_type = _workplace_from_text(rec.description[:1500])
    return rec if (rec.locations or rec.description) else None


# ── strategy selection + fetch ────────────────────────────────────────────────

_ORACLE_RE = re.compile(r"/hcmUI/CandidateExperience/([a-z]{2}(?:-[A-Za-z]{2})?)/sites/([A-Za-z0-9_]+)/job/(\d+)", re.I)
_SR_RE = re.compile(r"jobs\.smartrecruiters\.com/([^/]+)/(\d+)")
_GH_RE = re.compile(r"greenhouse\.io/([^/]+)/jobs/(\d+)")
_WD_JOB_RE = re.compile(r"myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+?)(?:/apply|/)?(?:[?#].*)?$")  # listing URLs may end in /apply
_NO_DETAIL_HOSTS = ("naukri.com", "hirist", "iimjobs.com", "foundit.in", "monsterindia", "indeed.com", "glassdoor")

_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}


def strategy_for(url: str) -> str:
    """oracle_api | workday_cxs | smartrecruiters_api | greenhouse_api | page | none"""
    host = urlsplit(url).netloc.lower()
    if any(h in host for h in _NO_DETAIL_HOSTS):
        return "none"
    if _ORACLE_RE.search(url):
        return "oracle_api"
    if _WD_JOB_RE.search(url):
        return "workday_cxs"
    if _SR_RE.search(url):
        return "smartrecruiters_api"
    if _GH_RE.search(url):
        return "greenhouse_api"
    return "page"


async def fetch_detail(url: str, client: httpx.AsyncClient, *, host_sem: asyncio.Semaphore, log: Any) -> DetailRecord:
    """Never raises. status: ok (locations or description found) | none | blocked | error."""
    strat = strategy_for(url)
    rec = DetailRecord(url=url, status="none")
    if strat == "none":
        return rec
    try:
        if strat == "oracle_api":
            m = _ORACLE_RE.search(url)
            host = urlsplit(url).netloc
            api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
            data = await request_json(client, "GET", api, host_sem=host_sem, log=log,
                                      params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{m.group(3)}",siteNumber={m.group(2)}'},
                                      headers={"Accept": "application/json"})
            parsed = parse_oracle_detail(data)
        elif strat == "workday_cxs":
            t = parse_target(url, "workday")
            m = _WD_JOB_RE.search(url)
            api = f"https://{t['host']}/wday/cxs/{t['tenant']}/{m.group(1)}{m.group(2)}"
            data = await request_json(client, "GET", api, host_sem=host_sem, log=log,
                                      headers={"Accept": "application/json", "Referer": f"https://{t['host']}/{m.group(1)}"})
            parsed = parse_workday_detail(data)
        elif strat == "smartrecruiters_api":
            m = _SR_RE.search(url)
            data = await request_json(client, "GET", f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}",
                                      host_sem=host_sem, log=log, headers={"Accept": "application/json"})
            parsed = parse_smartrecruiters_posting(data)
        elif strat == "greenhouse_api":
            m = _GH_RE.search(url)
            data = await request_json(client, "GET", f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}",
                                      host_sem=host_sem, log=log, headers={"Accept": "application/json"})
            parsed = parse_greenhouse_job(data)
        else:
            resp = await request(client, "GET", url, host_sem=host_sem, log=log, headers=_HTML_HEADERS)
            html = resp.text
            if looks_like_challenge(html):
                rec.status = "blocked"
                rec.error = "challenge page"
                return rec
            parsed = parse_jsonld(html) or parse_microdata(html)
    except FetchError as exc:
        msg = str(exc)
        rec.status = "blocked" if any(code in msg for code in ("HTTP 401", "HTTP 403", "HTTP 429")) else "error"
        rec.error = msg[:300]
        log.debug("detail.fetch_failed", url=url, status=rec.status, error=rec.error)
        return rec
    except Exception as exc:  # noqa: BLE001 — parser bugs must not take a run down
        rec.status = "error"
        rec.error = f"{type(exc).__name__}: {exc}"[:300]
        log.warning("detail.parse_failed", url=url, error=rec.error)
        return rec
    if parsed is None:
        rec.status = "none"
        return rec
    parsed.url = url
    parsed.status = "ok" if (parsed.locations or parsed.description) else "none"
    return parsed


def canonical_locations(rec: DetailRecord) -> list[str]:
    """Distinct canonical city keys ('bangalore', 'gurgaon') from a detail record."""
    seen: list[str] = []
    for l in rec.city_level():
        c = canonical_city(l.city)
        if c and c not in seen:
            seen.append(c)
    return seen
