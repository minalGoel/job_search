"""Turn (listing location, structured detail, LLM extraction) into one verdict.

Single source of truth for *where a job actually is* and whether it passes the user's
rule — "mentions NCR (any spelling) or is remote → in; only other locations → out;
hybrid counts only in NCR". Every gate that used to call
``is_acceptable_location(job.location)`` on the listing string now calls
:func:`passes` so the pipeline, the API and the dashboard never disagree.

Precedence: structured city-level locations (the job page / ATS detail API) beat the
LLM, which beats the listing string. The LLM only narrows — it is consulted when the
structured layer has no city.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from services.job_detail import DetailLocation, DetailRecord
from services.location_filter import (
    CITY_ALIASES,
    _tail_country,  # noqa: PLC2701 — same package family; the tail rule is the filter's
    canonical_city,
    explain,
    is_acceptable_location,
    is_ncr_city,
    work_mode as heuristic_work_mode,
)

_INDIA = {"in", "ind", "india", "republic of india"}


@dataclass
class Resolution:
    locations: list[str] = field(default_factory=list)   # display strings, one per place
    country: str = ""                                    # 'IN' | '<other>' | 'mixed' | ''
    work_mode: str = "unknown"                           # remote | hybrid | onsite | unknown
    remote_scope: str = "unknown"                        # india | global | other_country | unknown
    ncr_match: bool = False
    location_ok: bool = False
    source: str = "listing"                              # structured | llm | listing
    reason: str = ""

    def to_row(self) -> dict:
        return {
            "en_resolved_locations": "; ".join(self.locations),
            "en_resolved_country": self.country,
            "en_resolved_work_mode": self.work_mode,
            "en_remote_scope": self.remote_scope,
            "en_ncr_match": int(self.ncr_match),
            "en_location_ok": int(self.location_ok),
            "en_resolution_source": self.source,
            "en_location_reason": self.reason,
        }


def _is_india(country: str) -> Optional[bool]:
    c = (country or "").strip().lower().rstrip(".")
    if not c:
        return None
    return c in _INDIA


def _city_label(city: str) -> str:
    """Keep the source spelling unless an alias maps it elsewhere (Bengaluru → Bangalore)."""
    if not city:
        return ""
    canon = canonical_city(city)
    return canon.title() if canon != city.strip().lower() and canon in CITY_ALIASES.values() else city.strip()


def _display(loc: DetailLocation) -> str:
    parts = [_city_label(loc.city), loc.region, loc.country]
    return ", ".join(p for p in parts if p) or loc.raw


def _pick_work_mode(listing: str, title: str, description: str, detail: Optional[DetailRecord], llm: Optional[dict]) -> str:
    declared = (detail.workplace_type if detail else "") or ""
    if declared in ("remote", "hybrid", "onsite"):
        return declared
    text_mode = heuristic_work_mode(listing, title, (detail.description if detail and detail.description else description))
    if declared == "remote_or_hybrid":
        # JSON-LD TELECOMMUTE alone: the page says "remote allowed"; trust the text if it
        # says remote outright, otherwise call it hybrid (an office is still named).
        return "remote" if text_mode == "remote" else "hybrid"
    llm_mode = (llm or {}).get("work_mode") or ""
    if llm_mode in ("remote", "hybrid", "onsite"):
        return llm_mode
    return text_mode


def resolve(
    listing_location: str,
    *,
    title: str = "",
    description: str = "",
    detail: Optional[DetailRecord] = None,
    llm: Optional[dict] = None,
) -> Resolution:
    """Pure. `llm` is the *verified* extraction dict (cities/countries already checked
    against the text by services.llm_extractor)."""
    res = Resolution()
    listing = (listing_location or "").strip()

    # 1) which layer answers "where"?
    structured = detail.city_level() if detail and detail.status == "ok" else []
    llm_cities = [c for c in ((llm or {}).get("cities") or []) if c]
    if structured:
        res.source = "structured"
        res.locations = list(dict.fromkeys(_display(l) for l in structured))
        countries = {(_is_india(l.country)) for l in structured if l.country}
    elif llm_cities:
        res.source = "llm"
        res.locations = list(dict.fromkeys(_city_label(c) for c in llm_cities))
        countries = {_is_india(c) for c in ((llm or {}).get("countries") or []) if c}
    else:
        res.source = "listing"
        res.locations = [listing] if listing else []
        tail = _tail_country(listing.lower()) if listing else ""
        countries = {False} if tail else ({True} if "india" in listing.lower() else set())
        # a country-only structured record ("India") still tells us the country
        if detail and detail.status == "ok" and detail.locations:
            for l in detail.locations:
                if l.country and _is_india(l.country) is not None:
                    countries.add(_is_india(l.country))

    countries.discard(None)
    if countries == {True}:
        res.country = "IN"
    elif countries == {False}:
        res.country = "other"
    elif countries:
        res.country = "mixed"

    # 2) work mode + remote scope
    res.work_mode = _pick_work_mode(listing, title, description, detail, llm)
    res.remote_scope = (llm or {}).get("remote_scope") or "unknown"
    if res.remote_scope == "unknown" and res.work_mode == "remote":
        if res.country == "IN":
            res.remote_scope = "india"
        elif res.country == "other":
            res.remote_scope = "other_country"
        elif "india" in listing.lower():
            res.remote_scope = "india"
    where = f" ({'job page' if res.source == 'structured' else 'AI' if res.source == 'llm' else 'listing'})"

    # 3) country gate
    if res.country == "other" and not (res.work_mode == "remote" and res.remote_scope == "india"):
        res.location_ok = False
        res.reason = f"role is outside India: {'; '.join(res.locations) or listing}{where}"
        return res

    # 4) nothing but the listing string → exactly today's filter (its remote exclusions,
    #    "Remote - <US state>", country tails and city lists all apply)
    if res.source == "listing":
        res.location_ok = is_acceptable_location(listing)
        why = explain(listing)
        res.ncr_match = res.location_ok and "remote" not in why
        res.reason = why + where
        return res

    # 5) remote (structured/LLM said so): open to India, and the listing carries no
    #    regional restriction ("Remote - US only", "Remote (EMEA)")
    if res.work_mode == "remote":
        restricted = explain(listing).startswith("regional restriction") if listing else False
        if res.remote_scope in ("india", "global", "unknown") and not restricted:
            res.ncr_match = any(is_ncr_city(l.split(",")[0]) for l in res.locations)
            res.location_ok = True
            res.reason = f"remote ({res.remote_scope}){where}"
        else:
            res.location_ok = False
            res.reason = f"remote but restricted to another region{where}"
        return res

    # 6) hybrid / onsite / unknown: some named place must be NCR
    ncr = [l for l in res.locations if is_ncr_city(l.split(",")[0])]
    res.ncr_match = bool(ncr)
    if ncr:
        res.location_ok = True
        res.reason = f"{res.work_mode} in {ncr[0]}{where}"
    else:
        res.location_ok = False
        res.reason = f"{res.work_mode} in {'; '.join(res.locations)}{where} — not NCR"
    return res


_COARSE_REASONS = ("India (country-level)", "pure remote", "unrecognised", "empty")


def needs_detail(listing_location: str) -> bool:
    """Should the gate spend a detail request on this listing?

    Yes when the listing already passes (we keep it, so we want the real address) or when
    it is coarse — country-level "India", "3 Locations", "Remote", blank. No when it names a
    specific non-NCR city/state or another country: the listing is right about *that*.
    """
    listing = (listing_location or "").strip()
    if not listing or is_acceptable_location(listing):
        return True
    return explain(listing).startswith(_COARSE_REASONS)


def passes(listing_location: str, enrichment: Optional[dict[str, Any]]) -> bool:
    """The one predicate every gate uses: the stored verdict when we have one, else the
    listing-string rule (identical to today's behaviour for un-enriched jobs)."""
    if enrichment is not None:
        ok = enrichment.get("en_location_ok")
        if ok is not None:
            return bool(ok)
    return is_acceptable_location(listing_location)


def resolution_from_row(row: dict[str, Any]) -> Optional[dict]:
    """Compact dict for API consumers (None when the job has no enrichment)."""
    if not row or row.get("en_resolution_source") is None:
        return None
    return {
        "locations": row.get("en_resolved_locations") or "",
        "work_mode": row.get("en_resolved_work_mode") or "unknown",
        "ok": row.get("en_location_ok"),
        "source": row.get("en_resolution_source") or "",
        "reason": row.get("en_location_reason") or "",
    }


__all__ = ["Resolution", "resolve", "passes", "needs_detail", "resolution_from_row", "asdict"]
