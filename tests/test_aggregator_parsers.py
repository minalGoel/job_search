from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from pathlib import Path

import httpx

from config.search_params import SearchParams
from config.settings import Settings
from scrapers.adzuna import AdzunaScraper
from scrapers.base import ScraperSkipped
from scrapers.careerjet import CareerjetScraper
from scrapers.jooble import JoobleScraper
from services.title_filter import configure

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


class AdzunaParserTests(unittest.TestCase):
    def setUp(self) -> None:
        configure(SearchParams())
        self.addCleanup(configure, SearchParams())
        self.scraper = AdzunaScraper(None, SearchParams(), _settings(ADZUNA_APP_ID="x", ADZUNA_APP_KEY="y"))

    def test_parse_results(self) -> None:
        jobs = self.scraper._parse_results(_load("adzuna_sample.json")["results"])
        # 5001 (NCR, ok), 5003 (PMM — "anything with product" gate keeps it; UI category sorts it),
        # 5005 (Noida, ok); 5002 Bangalore and 5004 (no company) rejected
        self.assertEqual([j.title for j in jobs], ["Senior Product Manager - Payments", "Product Marketing Manager", "Group Product Manager"])
        first = jobs[0]
        self.assertEqual(first.platform, "adzuna")
        self.assertEqual(first.company, "Razorpay")
        self.assertNotIn("<strong>", first.title)
        self.assertNotIn("<strong>", first.description)
        # raw redirect kept (needs its params), id stable across tracking tokens
        self.assertIn("?se=", first.apply_link)
        self.assertEqual(first.posted_date, date(2026, 9, 15))
        self.assertEqual(first.salary, "₹30 - 45 LPA")
        self.assertEqual(jobs[2].salary, "₹40 LPA (est.)")
        self.assertEqual(jobs[2].posted_date, date(2026, 9, 13))

    def test_id_stable_across_tracking_params(self) -> None:
        items = _load("adzuna_sample.json")["results"][:1]
        a = self.scraper._parse_results(items)[0].id
        items[0]["redirect_url"] = items[0]["redirect_url"].replace("DEADBEEF", "CAFEBABE")
        b = self.scraper._parse_results(items)[0].id
        self.assertEqual(a, b)

    def test_scrape_uses_mock_transport_and_paginates(self) -> None:
        sample = _load("adzuna_sample.json")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json=sample)

        # Patch the client factory by running scrape with a transport-injecting subclass
        scraper = self.scraper
        orig_client = httpx.AsyncClient

        class _Client(orig_client):  # type: ignore[misc]
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        httpx.AsyncClient = _Client  # type: ignore[assignment]
        try:
            jobs = asyncio.run(scraper.scrape())
        finally:
            httpx.AsyncClient = orig_client  # type: ignore[assignment]
        self.assertEqual(len(calls), 1)  # count=5 < page size → single page
        self.assertEqual(len(jobs), 3)
        self.assertIn("title_only=product", calls[0])
        self.assertNotIn("where=", calls[0])  # location decided locally

    def test_missing_key_is_skip(self) -> None:
        scraper = AdzunaScraper(None, SearchParams(), _settings())
        with self.assertRaises(ScraperSkipped):
            asyncio.run(scraper.scrape())


class JoobleParserTests(unittest.TestCase):
    def setUp(self) -> None:
        configure(SearchParams())
        self.addCleanup(configure, SearchParams())
        self.scraper = JoobleScraper(None, SearchParams(), _settings(JOOBLE_API_KEY="k"))

    def test_parse_results(self) -> None:
        jobs = self.scraper._parse_results(_load("jooble_sample.json")["jobs"])
        # Urban Company ok; Tata Mumbai rejected; HCL project manager rejected; empty company rejected
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.company, "Urban Company")
        self.assertEqual(j.posted_date, date(2026, 9, 15))  # 7-digit fraction handled
        self.assertEqual(j.description, "Lead the product team")
        self.assertEqual(j.salary, "₹25L – ₹35L")
        self.assertIn("ckey=", j.apply_link)  # raw link kept


class CareerjetParserTests(unittest.TestCase):
    def setUp(self) -> None:
        configure(SearchParams())
        self.addCleanup(configure, SearchParams())
        self.scraper = CareerjetScraper(None, SearchParams(), _settings(CAREERJET_AFFID="aff"))

    def test_parse_results(self) -> None:
        jobs = self.scraper._parse_results(_load("careerjet_sample.json")["jobs"])
        self.assertEqual([j.company for j in jobs], ["MakeMyTrip"])  # Swiggy Bangalore, Maruti production rejected
        self.assertEqual(jobs[0].posted_date, date(2026, 9, 16))
        self.assertEqual(jobs[0].description, "Own growth products")

    def test_rfc2822_date(self) -> None:
        item = _load("careerjet_sample.json")["jobs"][1]
        item["locations"] = "Gurgaon, Haryana"
        jobs = self.scraper._parse_results([item])
        self.assertEqual(jobs[0].posted_date, date(2026, 9, 16))


if __name__ == "__main__":
    unittest.main()
