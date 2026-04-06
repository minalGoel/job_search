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
    title_keywords: list[str] = field(
        default_factory=lambda: ["product manager"]
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
