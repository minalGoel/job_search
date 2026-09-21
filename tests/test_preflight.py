from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from config.search_params import SearchParams
from config.settings import Settings
from models.job import Job
from scrapers import SCRAPER_REGISTRY
from scrapers.base import BaseScraper, ScraperSkipped
from services.preflight import (
    SKIP_PREFIX,
    needs_browser,
    partition,
    skip_reason,
    split_run_notes,
)


def _settings(**overrides) -> Settings:
    # _env_file=None: ignore the real .env so tests are deterministic
    return Settings(_env_file=None, **overrides)


class _SkippingScraper(BaseScraper):
    name = "dummy"
    uses_browser = False

    async def scrape(self) -> list[Job]:
        raise ScraperSkipped("nothing configured")


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cookies = Path(self._tmp.name)

    def test_login_gated_without_cookies_is_skipped(self) -> None:
        reason = skip_reason(SCRAPER_REGISTRY["cutshort"], _settings(), self.cookies)
        self.assertIsNotNone(reason)
        self.assertIn("no cookies", reason)
        self.assertIn("login cutshort", reason)

    def test_login_gated_with_cookies_runs(self) -> None:
        (self.cookies / "cutshort.json").write_text("{}")
        self.assertIsNone(skip_reason(SCRAPER_REGISTRY["cutshort"], _settings(), self.cookies))

    def test_missing_api_key_is_skipped(self) -> None:
        reason = skip_reason(SCRAPER_REGISTRY["adzuna"], _settings(), self.cookies)
        self.assertEqual(reason, "missing API key (ADZUNA_APP_ID, ADZUNA_APP_KEY) — set in .env")

    def test_api_key_present_runs(self) -> None:
        s = _settings(ADZUNA_APP_ID="x", ADZUNA_APP_KEY="y")
        self.assertIsNone(skip_reason(SCRAPER_REGISTRY["adzuna"], s, self.cookies))

    def test_no_login_scraper_runs(self) -> None:
        self.assertIsNone(skip_reason(SCRAPER_REGISTRY["remoteok"], _settings(), self.cookies))

    def test_needs_browser(self) -> None:
        self.assertFalse(needs_browser([SCRAPER_REGISTRY["remoteok"], SCRAPER_REGISTRY["adzuna"]]))
        self.assertTrue(needs_browser([SCRAPER_REGISTRY["remoteok"], SCRAPER_REGISTRY["naukri"]]))
        self.assertFalse(needs_browser([]))

    def test_partition(self) -> None:
        runnable, skipped, unknown = partition(
            ["remoteok", "cutshort", "adzuna", "nope"], SCRAPER_REGISTRY, _settings(), self.cookies
        )
        self.assertEqual(runnable, ["remoteok"])
        self.assertEqual(set(skipped), {"cutshort", "adzuna"})
        self.assertTrue(all(v.startswith(SKIP_PREFIX) for v in skipped.values()))
        self.assertEqual(unknown, ["nope"])

    def test_split_run_notes(self) -> None:
        real, skipped = split_run_notes({"naukri": "TimeoutError: x", "cutshort": f"{SKIP_PREFIX}no cookies"})
        self.assertEqual(real, {"naukri": "TimeoutError: x"})
        self.assertEqual(skipped, {"cutshort": "no cookies"})
        self.assertEqual(split_run_notes(None), ({}, {}))

    def test_safe_scrape_reports_skip_not_error(self) -> None:
        scraper = _SkippingScraper(None, SearchParams(), _settings())
        jobs, note = asyncio.run(scraper._safe_scrape())
        self.assertEqual(jobs, [])
        self.assertEqual(note, f"{SKIP_PREFIX}nothing configured")

    def test_get_page_without_browser_is_a_clear_error(self) -> None:
        scraper = _SkippingScraper(None, SearchParams(), _settings())
        with self.assertRaises(RuntimeError):
            asyncio.run(scraper._get_page("https://example.com"))

    def test_cookies_dir_is_absolute(self) -> None:
        scraper = _SkippingScraper(None, SearchParams(), _settings())
        self.assertTrue(scraper.cookies_dir.is_absolute())


if __name__ == "__main__":
    unittest.main()
