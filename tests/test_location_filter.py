from __future__ import annotations

import unittest

from services.location_filter import explain, is_acceptable_location, normalize_region, work_mode


class LocationFilterTests(unittest.TestCase):
    ACCEPT = [
        "Gurugram", "Gurgaon, Haryana, India", "Noida, Uttar Pradesh, India", "New Delhi", "Delhi NCR",
        "Remote", "Remote - India", "Work from Home — Anywhere", "India",
        "Remote - India / US",            # India explicitly included
        "Bangalore, Karnataka, India; Noida, Uttar Pradesh, India",  # multi-city incl. NCR
        "Pune / Gurgaon", "GGN", "Gurgoan", "Cyber City, Gurugram", "Greater Noida", "Manesar, Haryana",
        "Gurgaon (Hybrid)",
    ]
    REJECT = [
        "", None,
        "Bangalore", "Mumbai, Maharashtra, India", "Pune, IND",
        "London, UK", "San Francisco, CA", "Remote - US only", "Remote (US)",
        "Remote, US", "Remote - Estonia", "Ontario, CAN - Remote", "Remote - Poland",
        "3 Locations",                    # unresolved Workday multi-location text
        "Remote - EMEA", "Europe - Remote",
    ]

    def test_accept(self) -> None:
        for loc in self.ACCEPT:
            with self.subTest(loc=loc):
                self.assertTrue(is_acceptable_location(loc))

    def test_reject(self) -> None:
        for loc in self.REJECT:
            with self.subTest(loc=loc):
                self.assertFalse(is_acceptable_location(loc))

    def test_work_mode(self) -> None:
        self.assertEqual(work_mode("Gurgaon, India (Hybrid)"), "hybrid")
        self.assertEqual(work_mode("Remote - India"), "remote")
        self.assertEqual(work_mode("Noida", "Product Manager (Remote)"), "remote")
        self.assertEqual(work_mode("Gurugram"), "onsite")
        self.assertEqual(work_mode("Gurugram", "", "This is a hybrid role: 3 days in office."), "hybrid")
        self.assertEqual(work_mode("", "", ""), "unknown")

    def test_normalize_region(self) -> None:
        self.assertEqual(normalize_region("Gurgaon, India"), "delhi-ncr")
        self.assertEqual(normalize_region("Remote - India"), "remote")
        self.assertNotEqual(normalize_region("Remote, US"), "remote")
        self.assertEqual(normalize_region("Bengaluru"), "bengaluru")


if __name__ == "__main__":
    unittest.main()


class Sept2026LeakTests(unittest.TestCase):
    """Strings that were in the live DB as 'matched' on 2026-09-21 and shouldn't have been."""

    def test_country_at_the_tail_beats_an_ncr_token(self) -> None:
        for s in ("Muntinlupa, NCR, ph", "Taguig, National Capital Region (NCR), Philippines"):
            self.assertFalse(is_acceptable_location(s), s)
            self.assertIn("ends in non-India country", explain(s))
        self.assertNotEqual(normalize_region("Muntinlupa, NCR, ph"), "delhi-ncr")
        # but "India" anywhere still wins for multi-country posts, and an NCR city stays NCR
        self.assertTrue(is_acceptable_location("Remote - India / US"))
        self.assertTrue(is_acceptable_location("Gurugram · US shift"))

    def test_lowercase_iso_codes_and_full_country_names(self) -> None:
        for s in ("Bogotá, Bogotá, co (Remote)", "Athens, gr (Remote)", "Casablanca, Morocco",
                  "Casablanca, Morocco; Remote, Tunisia, 9999", "Remote - Estonia", "Sofia, Bulgaria"):
            self.assertFalse(is_acceptable_location(s), s)

    def test_remote_plus_us_state_is_a_us_role(self) -> None:
        for s in ("Remote - DC", "Remote in TX", "Remote (CA)", "WFH - NY"):
            self.assertFalse(is_acceptable_location(s), s)
        self.assertTrue(is_acceptable_location("Remote"))

    def test_diacritics_are_folded(self) -> None:
        self.assertTrue(is_acceptable_location("Faridabad, Haryāna, India"))
        self.assertFalse(is_acceptable_location("Nashik, Mahārāshtra, India"))
        self.assertTrue(is_acceptable_location("Bangalore, Karnātaka, India; Noida, Uttar Pradesh, India"))

    def test_non_ncr_indian_states_and_codes(self) -> None:
        for s in ("MH, India", "Karnataka, India", "Pune, MH", "Hyderabad, TS, India"):
            self.assertFalse(is_acceptable_location(s), s)
        # NCR-containing states stay open questions → still accepted at the listing level
        for s in ("Haryana, India", "Uttar Pradesh, India", "Noida, UP, IN, 201301 +10 more"):
            self.assertTrue(is_acceptable_location(s), s)

    def test_city_aliases(self) -> None:
        from services.location_filter import canonical_city, is_ncr_city

        self.assertEqual(canonical_city("Bengaluru"), "bangalore")
        self.assertEqual(canonical_city("Gurugram"), "gurgaon")
        self.assertTrue(is_ncr_city("Gurugram"))
        self.assertTrue(is_ncr_city("IND-Gurgaon (SVG)"))
        self.assertFalse(is_ncr_city("Bangalore"))
