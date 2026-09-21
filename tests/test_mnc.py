from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from config.search_params import SearchParams
from mnc_careers.ats.base import RawPosting
from mnc_careers.discovery import CSV_ALIASES, classify_against_registry, load_input_csv
from mnc_careers.filter import postings_to_jobs
from mnc_careers.registry import MNC, MNC_REGISTRY, platform_for
from mnc_careers.scraper import select_targets
from services.scoring import _company_slug
from services.title_filter import configure
from storage.db import JobDB


class FilterAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        configure(SearchParams())
        self.addCleanup(configure, SearchParams())

    def test_filters_title_then_location_and_never_defaults_location(self) -> None:
        mnc = MNC("Acme Corp", "https://acme.com", "Gurugram", "https://acme.wd1.myworkdayjobs.com/Ext")
        postings = [
            RawPosting("Senior Product Manager", "Gurugram, IND", "https://x/1"),
            RawPosting("Senior Product Manager", "Gurugram, IND", "https://x/1"),  # dupe url
            RawPosting("Software Engineer", "Gurugram, IND", "https://x/2"),      # title reject
            RawPosting("Product Manager", "London, UK", "https://x/3"),            # location reject
            RawPosting("Product Manager", "", "https://x/4"),                      # empty location → reject, never default
            RawPosting("Product Manager", "3 Locations", "https://x/5"),           # unresolved multi-location → reject
            RawPosting("", "Gurugram", "https://x/6"),                             # invalid
            RawPosting("Product Manager II", "Remote - India", "https://x/7", description="desc"),
        ]
        jobs, stats = postings_to_jobs(mnc, postings)
        self.assertEqual([j.apply_link for j in jobs], ["https://x/1", "https://x/7"])
        self.assertEqual((stats.fetched, stats.invalid, stats.dupes, stats.title_rejected, stats.location_rejected, stats.matched), (8, 1, 1, 1, 3, 2))
        self.assertEqual(jobs[0].platform, "mnc_acme_corp")
        self.assertEqual(jobs[0].company, "Acme Corp")
        self.assertEqual(jobs[0].description, "Direct from Acme Corp careers page")
        self.assertEqual(jobs[1].description, "desc")

    def test_platform_formula_is_stable(self) -> None:
        # Job.id depends on this exact string — see registry.platform_for
        self.assertEqual(platform_for(MNC("Twitter / X", "", "", "")), "mnc_twitter_/_x".replace("/", "_"))
        self.assertEqual(platform_for(MNC("EY (Ernst & Young)", "", "", "")), "mnc_ey_(ernst_&_young)")


class RegistryIntegrityTests(unittest.TestCase):
    def test_unique_names_and_slugs(self) -> None:
        names = [m.name for m in MNC_REGISTRY]
        self.assertEqual(len(names), len(set(n.lower() for n in names)), "duplicate MNC names")
        slugs = [_company_slug(m.name) for m in MNC_REGISTRY]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        self.assertFalse(dupes, f"duplicate company slugs: {dupes}")

    def test_urls_are_https(self) -> None:
        for m in MNC_REGISTRY:
            for u in (m.careers_url, m.pm_search_url, m.api_url):
                if u:
                    self.assertTrue(u.startswith("https://") or u.startswith("http://"), f"{m.name}: {u}")

    def test_api_type_values_are_known(self) -> None:
        from mnc_careers.ats import FETCHERS
        from mnc_careers.ats.detect import HTML_ONLY

        for m in MNC_REGISTRY:
            if m.api_type:
                self.assertIn(m.api_type, set(FETCHERS) | set(HTML_ONLY), f"{m.name}: unknown api_type {m.api_type}")

    def test_every_input_csv_company_is_accounted_for(self) -> None:
        """Every row of mnc_input.csv is exact/alias in the registry, or (until discovery lands) 'new'."""
        results = classify_against_registry(load_input_csv())
        for alias, registry_name in CSV_ALIASES.items():
            self.assertIn(registry_name, [m.name for m in MNC_REGISTRY], f"alias target missing: {registry_name}")
        self.assertEqual(len(results), 209)
        for r in results:
            if r.classification in ("exact", "alias"):
                self.assertTrue(r.registry_name)

    def test_hq_country_present_for_csv_companies_in_registry(self) -> None:
        results = classify_against_registry(load_input_csv())
        by_name = {m.name: m for m in MNC_REGISTRY}
        missing = [r.registry_name for r in results if r.classification in ("exact", "alias") and not by_name[r.registry_name].hq_country]
        self.assertFalse(missing, f"registry entries from the CSV without hq_country: {missing[:10]}")


class SelectTargetsTests(unittest.TestCase):
    def test_only_is_whole_word_or_slug(self) -> None:
        names = [m.name for m in select_targets(MNC_REGISTRY, only=["SAP"])]
        self.assertIn("SAP", names)
        self.assertNotIn("Publicis Sapient", names)

    def test_only_resolves_csv_alias(self) -> None:
        names = [m.name for m in select_targets(MNC_REGISTRY, only=["Moody's"], aliases=CSV_ALIASES)]
        self.assertIn("Moody's Analytics", names)

    def test_ats_filter(self) -> None:
        for m in select_targets(MNC_REGISTRY, ats="workday"):
            self.assertEqual(m.ats_type, "workday")


class SourceRunsTests(unittest.TestCase):
    def test_source_runs_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = JobDB(db_path=Path(tmp) / "jobs.db")
            try:
                db.save_source_runs("mnc", [
                    {"name": "Acme", "ats": "workday", "lane": "api", "status": "ok", "fetched": 10, "total_reported": 10, "matched": 2, "inserted": 1},
                    {"name": "Beta", "ats": "html", "lane": "html", "status": "failed", "error": "timeout"},
                ], "batch-1")
                db.save_source_runs("mnc", [{"name": "Acme", "ats": "workday", "lane": "api", "status": "empty"}], "batch-2")
                latest = db.get_latest_source_runs("mnc")
                self.assertEqual(latest["Acme"]["status"], "empty")
                self.assertEqual(latest["Acme"]["batch_id"], "batch-2")
                self.assertEqual(latest["Beta"]["error"], "timeout")
                batches = db.get_source_run_batches("mnc")
                self.assertEqual([b["batch_id"] for b in batches], ["batch-2", "batch-1"])
                self.assertEqual(batches[1]["failed"], 1)
                # runs table untouched — "last run" is never hijacked by an MNC batch
                self.assertIsNone(db.get_last_run())
            finally:
                db.close()

    def test_old_db_gets_source_runs_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL)")
            conn.commit(); conn.close()
            db = JobDB(db_path=path)
            try:
                tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("source_runs", tables)
            finally:
                db.close()


class ScoringSignalsTests(unittest.TestCase):
    """New signals from the Sept 2026 decisions: work-mode preference + target-MNC bonus."""

    def test_remote_hybrid_bonus_and_target_mnc(self) -> None:
        import json

        from services.scoring import score_job

        base = {"title": "Senior Product Manager", "company": "Acme", "platform": "mnc_acme", "description": ""}
        onsite = score_job({**base, "location": "Gurugram"}, {"is_mnc": 1})
        hybrid = score_job({**base, "location": "Gurugram (Hybrid)"}, {"is_mnc": 1})
        remote = score_job({**base, "location": "Remote - India"}, {"is_mnc": 1})
        self.assertGreater(hybrid["relevance_score"], onsite["relevance_score"])
        self.assertGreater(remote["relevance_score"], onsite["relevance_score"])
        self.assertIn("hybrid_role", json.loads(hybrid["score_reasons"]))
        self.assertIn("remote_role", json.loads(remote["score_reasons"]))

        plain = score_job({**base, "location": "Gurugram"}, {"is_mnc": 1})
        target = score_job({**base, "location": "Gurugram"}, {"is_mnc": 1, "hq_country": "Germany"})
        self.assertGreater(target["company_quality_score"], plain["company_quality_score"])
        self.assertIn("target_mnc", json.loads(target["score_reasons"]))

    def test_non_pm_product_titles_are_demoted_not_dropped(self) -> None:
        from services.scoring import score_job

        pm = score_job({"title": "Senior Product Manager", "company": "Acme", "location": "Gurugram", "platform": "naukri", "description": ""})
        pmm = score_job({"title": "Product Marketing Manager", "company": "Acme", "location": "Gurugram", "platform": "naukri", "description": ""})
        self.assertGreater(pm["relevance_score"], pmm["relevance_score"])


class HqCountryProfileTests(unittest.TestCase):
    def test_hq_country_column_and_coalesce(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = JobDB(db_path=Path(tmp) / "jobs.db")
            try:
                cols = {r[1] for r in db.conn.execute("PRAGMA table_info(company_profiles)").fetchall()}
                self.assertIn("hq_country", cols)
                db.upsert_company_profile({"normalized_company": "acme", "company_display_name": "Acme", "is_mnc": 1, "hq_country": "Germany"})
                db.upsert_company_profile({"normalized_company": "acme", "company_display_name": "Acme", "is_mnc": 1})  # blank must not wipe it
                prof = db.get_all_company_profiles()["acme"]
                self.assertEqual(prof["hq_country"], "Germany")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
