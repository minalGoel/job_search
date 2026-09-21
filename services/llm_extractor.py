"""Local-LLM extraction (Ollama) for what structured data can't answer.

The model reads a posting's text and returns a small, flat JSON document — cities,
countries, work mode, remote scope, seniority, role type, years of experience — plus the
sentences it based the location/work-mode answers on. **The model proposes; code
verifies**: every city/country must literally occur in the input text (after alias and
diacritic folding), the location evidence must be a substring of the input *and* contain
the city, and anything that fails is dropped. Temperature 0, grammar-constrained output
(``format: <schema>``, Ollama ≥ 0.5), one retry on invalid JSON.

Skips (never fails) when Ollama is down or the model is missing — the structured layer
still does its job. Runtime on a 16 GB Apple-Silicon laptop with qwen2.5:3b: ~3–6 s per
job after the first (model-load) call.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from services.location_filter import CITY_ALIASES, NON_INDIA_COUNTRIES, NON_INDIA_COUNTRY_CODES, canonical_city

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cities": {"type": "array", "items": {"type": "string"}},
        "countries": {"type": "array", "items": {"type": "string"}},
        "work_mode": {"type": "string", "enum": ["onsite", "hybrid", "remote", "unknown"]},
        "remote_scope": {"type": "string", "enum": ["india", "global", "other_country", "unknown"]},
        "seniority": {"type": "string", "enum": ["intern", "junior", "mid", "senior", "lead", "director", "vp", "unknown"]},
        "role_type": {"type": "string", "enum": ["product_manager", "product_owner", "product_marketing", "product_design",
                                                  "product_analyst", "engineering", "sales", "other"]},
        "years_min": {"type": ["integer", "null"]},
        "years_max": {"type": ["integer", "null"]},
        "evidence_location": {"type": "string"},
        "evidence_work_mode": {"type": "string"},
    },
    "required": ["cities", "countries", "work_mode", "remote_scope", "seniority", "role_type",
                 "years_min", "years_max", "evidence_location", "evidence_work_mode"],
}

SYSTEM_PROMPT = (
    "You extract facts from one job posting. Rules: copy city and country names VERBATIM from the text; "
    "cities = only the cities where THIS role is based (not every office the company mentions); "
    "never invent a place; if the text does not state something, answer 'unknown' (or null for numbers). "
    "work_mode is remote only when the role itself is remote, hybrid when the role mixes office and home, "
    "onsite when an office is required. remote_scope says who a remote role is open to. "
    "evidence_location and evidence_work_mode must be short exact quotes from the text."
)

PLACEHOLDER_DESCRIPTIONS = ("direct from ", "via ", "yc-backed startup")


@dataclass
class LLMResult:
    status: str                     # ok | unverified | skipped | error
    data: dict = field(default_factory=dict)   # verified extraction (schema keys)
    model: str = ""
    error: str = ""
    latency_ms: int = 0
    dropped: list[str] = field(default_factory=list)   # values the verifier removed


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()


def is_placeholder_description(description: str) -> bool:
    d = (description or "").strip().lower()
    return not d or len(d) < 40 or d.startswith(PLACEHOLDER_DESCRIPTIONS)


def build_input(title: str, company: str, listing_location: str, description: str, structured_locations: list[str], *, max_chars: int) -> str:
    desc = re.sub(r"\s+", " ", description or "").strip()[:max_chars]
    parts = [f"Title: {title}", f"Company: {company}", f"Description: {desc or '(none)'}", f"Listing location: {listing_location or '(none)'}"]
    if structured_locations:
        parts.append("Structured locations from the job page: " + "; ".join(structured_locations))
    return "\n".join(parts)


def _mentions(text_folded: str, value: str) -> bool:
    v = _fold(value).strip()
    if not v:
        return False
    if v in text_folded:
        return True
    canon = canonical_city(value)
    # 'Bengaluru' is verified by 'Bangalore' in the text and vice versa
    return any(_fold(alias) in text_folded for alias, c in CITY_ALIASES.items() if c == canon)


def verify(raw: dict, input_text: str) -> tuple[dict, list[str]]:
    """Drop anything the text doesn't back. Returns (clean, dropped)."""
    folded = _fold(input_text)
    dropped: list[str] = []
    clean: dict[str, Any] = {}
    cities = [c.strip() for c in (raw.get("cities") or []) if isinstance(c, str) and c.strip()]
    ev_loc = str(raw.get("evidence_location") or "").strip()
    ev_ok = bool(ev_loc) and _fold(ev_loc) in folded
    kept_cities: list[str] = []
    _country_words = set(NON_INDIA_COUNTRIES) | set(NON_INDIA_COUNTRY_CODES) | {"india", "in", "ind"}
    for c in cities:
        if len(c.strip()) <= 3 or _fold(c).strip() in _country_words:
            dropped.append(f"city:{c}(country)")        # 3B models file countries under cities; boilerplate, drop
        elif not _mentions(folded, c):
            dropped.append(f"city:{c}")                 # not in the text at all → invented
        elif ev_ok and not _mentions(_fold(ev_loc), c) and len(cities) == 1:
            dropped.append(f"city:{c}(evidence)")       # the quoted sentence names no such city → boilerplate
        else:
            kept_cities.append(c)
    clean["cities"] = list(dict.fromkeys(kept_cities))
    countries = [c.strip() for c in (raw.get("countries") or []) if isinstance(c, str) and c.strip()]
    clean["countries"] = [c for c in countries if _mentions(folded, c)]
    dropped += [f"country:{c}" for c in countries if c not in clean["countries"]]
    for key, allowed in (("work_mode", ("onsite", "hybrid", "remote", "unknown")),
                         ("remote_scope", ("india", "global", "other_country", "unknown")),
                         ("seniority", ("intern", "junior", "mid", "senior", "lead", "director", "vp", "unknown")),
                         ("role_type", ("product_manager", "product_owner", "product_marketing", "product_design", "product_analyst", "engineering", "sales", "other"))):
        v = str(raw.get(key) or "").strip().lower()
        clean[key] = v if v in allowed else ("unknown" if "unknown" in allowed else "other")
    for key in ("years_min", "years_max"):
        v = raw.get(key)
        clean[key] = int(v) if isinstance(v, (int, float)) and 0 <= v <= 40 else None
    if clean["years_min"] is not None and clean["years_max"] is not None and clean["years_max"] < clean["years_min"]:
        clean["years_max"] = None
    clean["evidence_location"] = ev_loc if ev_ok else ""
    ev_wm = str(raw.get("evidence_work_mode") or "").strip()
    clean["evidence_work_mode"] = ev_wm if ev_wm and _fold(ev_wm) in folded else ""
    if clean["work_mode"] != "unknown" and not clean["evidence_work_mode"]:
        # keep the mode (it's an enum over the whole text) but flag it as unquoted
        clean["work_mode_unquoted"] = True
    return clean, dropped


class OllamaExtractor:
    def __init__(self, *, url: str, model: str, timeout: int = 90, num_ctx: int = 4096, max_input_chars: int = 3000) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.max_input_chars = max_input_chars
        self._client = httpx.Client(timeout=timeout)

    # ── preflight ──
    def status(self) -> tuple[bool, str]:
        """(ok, reason). Never raises."""
        try:
            r = self._client.get(f"{self.url}/api/tags", timeout=3)
        except httpx.HTTPError as exc:
            return False, f"Ollama not reachable at {self.url} ({type(exc).__name__}) — brew install ollama && brew services start ollama"
        if r.status_code != 200:
            return False, f"Ollama answered HTTP {r.status_code}"
        names = {m.get("name", "") for m in r.json().get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return False, f"model {self.model!r} not pulled — ollama pull {self.model}"
        return True, "ok"

    # ── one extraction ──
    def extract(self, *, title: str, company: str, listing_location: str, description: str, structured_locations: Optional[list[str]] = None) -> LLMResult:
        text = build_input(title, company, listing_location, description, structured_locations or [], max_chars=self.max_input_chars)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
            "keep_alive": "10m",
        }
        t0 = time.monotonic()
        last_err = ""
        for attempt in (1, 2):
            try:
                r = self._client.post(f"{self.url}/api/chat", json=body)
                r.raise_for_status()
                content = (r.json().get("message") or {}).get("content") or ""
                raw = json.loads(content)
                if not isinstance(raw, dict):
                    raise ValueError("not an object")
            except (httpx.HTTPError, ValueError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"[:200]
                continue
            clean, dropped = verify(raw, text)
            ms = int((time.monotonic() - t0) * 1000)
            status = "ok" if (clean["cities"] or clean["countries"] or clean["work_mode"] != "unknown" or clean["seniority"] != "unknown") else "unverified"
            return LLMResult(status=status, data=clean, model=self.model, latency_ms=ms, dropped=dropped)
        return LLMResult(status="error", model=self.model, error=last_err, latency_ms=int((time.monotonic() - t0) * 1000))

    def close(self) -> None:
        self._client.close()
