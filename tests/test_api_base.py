from __future__ import annotations

import unittest
from datetime import date

from scrapers.api_base import (
    format_inr_salary,
    parse_epoch,
    parse_iso_date,
    stable_job_id,
    stable_link,
    strip_html,
)


class ApiBaseTests(unittest.TestCase):
    def test_stable_link_drops_query_and_fragment(self) -> None:
        self.assertEqual(
            stable_link("https://www.adzuna.in/land/ad/5001?se=abc&v=DEADBEEF#x"),
            "https://www.adzuna.in/land/ad/5001",
        )
        self.assertEqual(stable_link("https://example.com/?a=1"), "https://example.com/?a=1")
        self.assertEqual(stable_link(""), "")

    def test_stable_job_id_ignores_tracking_params(self) -> None:
        a = stable_job_id("adzuna", "Razorpay", "Product Manager", "https://x.in/land/ad/1?v=A")
        b = stable_job_id("adzuna", "Razorpay", "Product Manager", "https://x.in/land/ad/1?v=B")
        c = stable_job_id("adzuna", "Razorpay", "Product Manager", "https://x.in/land/ad/2?v=A")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 16)

    def test_strip_html(self) -> None:
        self.assertEqual(strip_html("Senior <strong>Product</strong>  Manager &amp; Lead"), "Senior Product Manager & Lead")
        self.assertEqual(strip_html(None), "")

    def test_parse_iso_date_variants(self) -> None:
        self.assertEqual(parse_iso_date("2026-09-15T10:22:31Z"), date(2026, 9, 15))
        self.assertEqual(parse_iso_date("2026-09-15T00:00:00.0000000"), date(2026, 9, 15))  # 7-digit fraction
        self.assertEqual(parse_iso_date("2026-09-16 07:54:07"), date(2026, 9, 16))
        self.assertEqual(parse_iso_date("Tue, 16 Sep 2026 07:54:07 GMT"), date(2026, 9, 16))
        self.assertIsNone(parse_iso_date("garbage"))
        self.assertIsNone(parse_iso_date(None))
        self.assertIsNone(parse_iso_date(""))

    def test_parse_epoch_seconds_and_millis(self) -> None:
        self.assertEqual(parse_epoch(1789497000), date(2026, 9, 15))
        self.assertEqual(parse_epoch(1789497000000), date(2026, 9, 15))
        self.assertEqual(parse_epoch("1789497000000"), date(2026, 9, 15))
        self.assertIsNone(parse_epoch(None))
        self.assertIsNone(parse_epoch("x"))
        self.assertIsNone(parse_epoch(0))

    def test_format_inr_salary(self) -> None:
        self.assertEqual(format_inr_salary(3000000, 4500000), "₹30 - 45 LPA")
        self.assertEqual(format_inr_salary(4000000, 4000000, predicted=True), "₹40 LPA (est.)")
        self.assertIsNone(format_inr_salary(0, 0))
        self.assertIsNone(format_inr_salary(None, 100))
        self.assertIsNone(format_inr_salary("a", "b"))


if __name__ == "__main__":
    unittest.main()
