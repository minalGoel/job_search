"""
services/title_filter.py — Single source of truth for job title relevance.

All filtering is *ours*: portals' search boxes are treated as volume hints,
never as the decision. Every ingestion path ends in ``JobDB.insert_job()``,
which calls :func:`is_relevant_title`; the pipeline gate in ``main._run_all``
and the MNC/VC/aggregator scrapers call it too (defense in depth).

Rules are config-driven via :class:`config.search_params.SearchParams`:

1. empty title                                   → reject
2. contains a MULTI-WORD accept phrase as
   contiguous tokens (``titles``, e.g.
   "product manager")                            → accept  (beats exclusions)
3. contains an exclude phrase (token-boundary)   → reject
4. contains a single-token accept phrase
   (``title_keywords``, e.g. "product")          → accept
5. every token of some accept phrase fuzzy-matches
   a title token (``rapidfuzz.fuzz.ratio`` ≥
   ``title_token_fuzz_threshold``)               → accept  (typo tolerance)
6. otherwise                                     → reject

Current defaults (Sept 2026, user decision): the gate is the single token
"product" — "anything with Product works; the rest shows up as filters in the
UI". :func:`categorize` buckets accepted titles (product_manager,
product_leadership, product_owner, product_marketing, …) for the dashboard
and ``config/scoring_rules.TITLE_WEIGHTS`` demotes the non-PM families.
"Production Manager" still fails: per-token ``fuzz.ratio("product",
"production") = 82`` is below the 85 threshold. Whole-phrase fuzzy scorers
(``token_set_ratio``) are deliberately NOT used — they rate "production
manager" at 90+ against "product manager".

``main.py`` calls :func:`configure` once with the process-wide
``SearchParams``. Other processes (e.g. ``api/server.py``) never call it and
get the dataclass defaults, which are identical — do not "fix" that.
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

from config.search_params import SearchParams

_params: SearchParams = SearchParams()
_accept_phrases: list[tuple[str, ...]] = []
_exclude_phrases: list[tuple[str, ...]] = []

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def configure(params: SearchParams) -> None:
    """Bind the SearchParams that drive title matching (idempotent)."""
    global _params, _accept_phrases, _exclude_phrases
    _params = params
    seen: set[tuple[str, ...]] = set()
    accept: list[tuple[str, ...]] = []
    for phrase in list(params.title_keywords) + list(params.titles):
        toks = _tokens(phrase)
        if toks and toks not in seen:
            seen.add(toks)
            accept.append(toks)
    _accept_phrases = accept
    _exclude_phrases = [t for t in (_tokens(p) for p in params.title_exclude_phrases) if t]


def current_params() -> SearchParams:
    """The SearchParams currently bound (for scrapers that need the query string)."""
    return _params


def _tokens(text: Optional[str]) -> tuple[str, ...]:
    """Lowercase, strip punctuation, split, expand synonyms per token."""
    if not text:
        return ()
    syn = _params.title_synonyms
    return tuple(syn.get(t, t) for t in _NON_ALNUM.sub(" ", text.lower()).split() if t)


def _contains_phrase(title_toks: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    if n == 0 or n > len(title_toks):
        return False
    return any(title_toks[i : i + n] == phrase for i in range(len(title_toks) - n + 1))


def _fuzzy_phrase_match(title_toks: tuple[str, ...], phrase: tuple[str, ...]) -> list[tuple[str, str, float]]:
    """For each phrase token find the best title token; return pairs if all pass."""
    threshold = _params.title_token_fuzz_threshold
    pairs: list[tuple[str, str, float]] = []
    for ptok in phrase:
        best: tuple[str, float] = ("", 0.0)
        for ttok in title_toks:
            score = fuzz.ratio(ptok, ttok)
            if score > best[1]:
                best = (ttok, score)
        if best[1] < threshold:
            return []
        pairs.append((ptok, best[0], best[1]))
    return pairs


def _evaluate(title: Optional[str]) -> tuple[bool, str]:
    if not title or not title.strip():
        return False, "empty"
    toks = _tokens(title)
    if not toks:
        return False, "empty"
    # Multi-word accept phrases ("product manager") win over exclusions so that
    # "Product Manager – Production Tools" is never killed by an exclusion.
    for phrase in _accept_phrases:
        if len(phrase) > 1 and _contains_phrase(toks, phrase):
            return True, f"exact phrase: '{' '.join(phrase)}'"
    for phrase in _exclude_phrases:
        if _contains_phrase(toks, phrase):
            return False, f"excluded phrase: '{' '.join(phrase)}'"
    # Single-token accept phrases ("product") are checked after exclusions so a
    # configured exclusion like "product marketing" can still apply.
    for phrase in _accept_phrases:
        if len(phrase) == 1 and _contains_phrase(toks, phrase):
            return True, f"exact phrase: '{' '.join(phrase)}'"
    for phrase in _accept_phrases:
        pairs = _fuzzy_phrase_match(toks, phrase)
        if pairs:
            detail = ", ".join(f"{p}~{t}({s:.0f})" for p, t, s in pairs)
            return True, f"fuzzy tokens: {detail}"
    return False, "no match"


# Title categories for UI filtering / scoring. First match wins; order matters.
TITLE_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("product_marketing", ("product marketing",)),
    ("product_design", ("product design", "product designer", "ux", "user experience")),
    ("product_owner", ("product owner",)),
    ("product_analyst_ops", ("product analyst", "product analytics", "product operations", "product ops",
                             "product support", "product specialist", "product data", "product research")),
    ("product_engineering", ("product engineer", "product developer", "product security", "product architect")),
    ("product_leadership", ("head of product", "director of product", "director, product", "director product",
                            "vp product", "vp of product", "vice president product", "vice president, product",
                            "chief product", "cpo", "gm product", "general manager product", "product director",
                            "senior director", "avp product", "svp product")),
    ("product_manager", ("product manager", "product management", "product lead", "principal pm", "senior pm",
                         "group pm", "lead pm", "staff pm", "technical pm", "growth pm", "pm ii", "pm 2")),
]


def categorize(title: Optional[str]) -> str:
    """Bucket a (product) title for UI filters: product_manager, product_leadership,
    product_owner, product_marketing, product_design, product_analyst_ops,
    product_engineering, other_product, or '' when the title is not product-related."""
    toks = _tokens(title)
    if not toks:
        return ""
    for cat, phrases in TITLE_CATEGORIES:
        for ph in phrases:
            if _contains_phrase(toks, _tokens(ph)):
                return cat
    return "other_product" if "product" in toks or any(fuzz.ratio("product", t) >= _params.title_token_fuzz_threshold for t in toks) else ""


def is_relevant_title(title: Optional[str]) -> bool:
    """Return True if *title* is a target role under the configured rules."""
    return _evaluate(title)[0]


def explain_title(title: Optional[str]) -> str:
    """Human-readable reason for the accept/reject decision (for logs)."""
    return _evaluate(title)[1]


# Bind defaults at import so callers that never call configure() still work.
configure(_params)
