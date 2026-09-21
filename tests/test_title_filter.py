from __future__ import annotations

import unittest

from config.search_params import SearchParams
from services.title_filter import categorize, configure, explain_title, is_relevant_title

# Default gate (user decision, Sept 2026): "anything with Product works; the rest
# shows up as filters in the UI" → token "product" (typo-tolerant), no exclusions.
ACCEPT = [
    "Senior Product Manager",
    "Product Manager II",
    "Group Product Manager",
    "Lead Product Manager - Payments",
    "Sr. Product Manager",
    "Product Mgr",
    "Prodcut Manager",  # typo tolerance (per-token ratio 85.7)
    "Technical Product Manager",
    "Associate Product Manager",  # accepted here; scoring demotes it
    "PRODUCT MANAGER",
    "Product Manager - Production Planning Tools",
    "Products Specialist",
    "Head of Product",
    "Director, Product Management",
    "VP Product",
    "Product Owner",
    "Product Marketing Manager",
    "Product Designer",
    "Product Lead",
]

REJECT = [
    "Production Manager",  # production~product = 82 < 85
    "Project Manager",
    "Program Manager",
    "Manager - Production Planning",
    "Software Engineer",
    "Productive Workforce Coordinator",  # productive~product = 82 < 85
    "",
    None,
]

CATEGORIES = {
    "Senior Product Manager": "product_manager",
    "Director, Product Management": "product_leadership",
    "Head of Product": "product_leadership",
    "VP, Product": "product_leadership",
    "Senior Director, Product": "product_leadership",
    "Product Owner": "product_owner",
    "Product Marketing Manager": "product_marketing",
    "Senior Product Designer": "product_design",
    "Product Analyst": "product_analyst_ops",
    "Product Support Specialist": "product_analyst_ops",
    "Product Engineer": "product_engineering",
    "Product Lead": "product_manager",
    "Products Specialist": "other_product",
    "Software Engineer": "",
    "": "",
}


class TitleFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        configure(SearchParams())
        self.addCleanup(configure, SearchParams())

    def test_accepts_product_titles(self) -> None:
        for title in ACCEPT:
            with self.subTest(title=title):
                self.assertTrue(is_relevant_title(title), explain_title(title))

    def test_rejects_non_product_titles(self) -> None:
        for title in REJECT:
            with self.subTest(title=title):
                self.assertFalse(is_relevant_title(title), explain_title(title))

    def test_categorize(self) -> None:
        for title, cat in CATEGORIES.items():
            with self.subTest(title=title):
                self.assertEqual(categorize(title), cat)

    def test_explain_prefixes(self) -> None:
        self.assertEqual(explain_title(""), "empty")
        self.assertTrue(explain_title("Product Manager").startswith("exact phrase:"))
        self.assertTrue(explain_title("Prodcut Manager").startswith("fuzzy tokens:"))
        self.assertEqual(explain_title("Software Engineer"), "no match")

    def test_is_config_driven(self) -> None:
        configure(SearchParams(titles=["Head of Product"], title_keywords=["head of product"]))
        self.assertTrue(is_relevant_title("Head of Product"))
        self.assertFalse(is_relevant_title("Product Manager"))

    def test_exclusions_are_config_driven(self) -> None:
        configure(SearchParams(title_exclude_phrases=["product marketing", "product owner"]))
        self.assertFalse(is_relevant_title("Product Marketing Manager"))
        self.assertTrue(explain_title("Product Owner").startswith("excluded phrase:"))
        self.assertTrue(is_relevant_title("Product Manager"))

    def test_strict_pm_gate_still_available(self) -> None:
        # The previous default is one config line away.
        configure(SearchParams(title_keywords=["product manager"], title_exclude_phrases=["production", "product marketing"]))
        self.assertTrue(is_relevant_title("Senior Product Manager"))
        self.assertFalse(is_relevant_title("Head of Product"))
        self.assertFalse(is_relevant_title("Product Marketing Manager"))


if __name__ == "__main__":
    unittest.main()
