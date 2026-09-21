from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchParams:
    titles: list[str] = field(
        default_factory=lambda: [
            "Product Manager",
            "Product Manager II",
            "Senior Product Manager",
        ]
    )
    # Accept phrases for the title filter (services/title_filter.py). The user's
    # rule (Sept 2026): "anything with Product works; the rest shows up as filters
    # in the UI" — so the gate is the single token "product" (typo-tolerant) and
    # sorting PM vs leadership vs owner vs marketing happens via title categories.
    title_keywords: list[str] = field(
        default_factory=lambda: ["product"]
    )
    experience_min: int = 5
    experience_max: int = 7
    location: str = "Delhi NCR"
    location_variants: list[str] = field(
        default_factory=lambda: [
            "Delhi NCR",
            "Delhi",
            "Gurugram",
            "Gurgaon",
            "Noida",
            "New Delhi",
        ]
    )
    industries: list[str] = field(
        default_factory=lambda: [
            "Technology",
            "SaaS",
            "B2B",
            "Software",
            "Internet",
        ]
    )
    min_ctc_lpa: int = 40

    # ---- Title filtering (services/title_filter.py reads these) ----------
    # A title is accepted if it contains one of title_keywords/titles as a
    # contiguous phrase, or (after exclusions) every token of a keyword phrase
    # fuzzy-matches a title token (typo tolerance). Exclusions reject titles
    # that share a token with the keyword but mean something else.
    # Deliberately empty: "Product Marketing", "Product Owner" etc. are kept and
    # surfaced through title categories + UI filters instead of being dropped.
    # ("production"/"project manager" never match the token "product" anyway.)
    title_exclude_phrases: list[str] = field(default_factory=list)
    # Per-token normalisation before matching (lowercase, punctuation stripped).
    title_synonyms: dict[str, str] = field(
        default_factory=lambda: {
            "mgr": "manager",
            "mgmt": "management",
            "sr": "senior",
            "snr": "senior",
            "jr": "junior",
        }
    )
    # rapidfuzz.fuzz.ratio threshold for per-token typo tolerance
    # ("prodcut"~"product" = 85.7 passes; "production"~"product" = 82.4 fails).
    title_token_fuzz_threshold: int = 85
    # Server-side keyword "net" used ONLY when a company portal has more
    # postings than MNC_MAX_POSTINGS (see mnc_careers). Local filtering is
    # still applied to everything that comes back.
    server_net_keywords: list[str] = field(default_factory=lambda: ["product"])
