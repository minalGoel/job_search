from __future__ import annotations

import unittest

from services.location_filter import is_acceptable_location, normalize_region, work_mode


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
