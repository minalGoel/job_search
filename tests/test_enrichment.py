from __future__ import annotations

import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from models.job import Job
from services.llm_extractor import build_input, is_placeholder_description, verify
from storage.db import JobDB


def _job(**kw) -> Job:
    base = dict(title="Senior Product Manager", company="Acme", location="India (Hybrid)", platform="mnc_acme",
                apply_link="https://acme.example/jobs/1", description="Direct from Acme careers page")
    base.update(kw)
    return Job(**base)


class EnrichmentDbTests(unittest.TestCase):
    def test_table_upsert_partial_and_cascade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.db"
            conn = sqlite3.connect(path)   # old schema: no job_enrichment table
            conn.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL)")
            conn.commit(); conn.close()
            db = JobDB(db_path=path)
            try:
                tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("job_enrichment", tables)
                j = _job(); db.insert_job(j)
                db.upsert_enrichment(j.id, {"en_detail_source": "oracle_api", "en_detail_status": "ok",
                                            "en_locations_json": [{"city": "Bangalore"}], "en_location_ok": 0})
                db.upsert_enrichment(j.id, {"en_llm_status": "ok", "en_seniority": "senior"})   # partial: keeps the rest
                row = db.get_enrichment(j.id)
                self.assertEqual((row["en_detail_source"], row["en_location_ok"], row["en_seniority"]), ("oracle_api", 0, "senior"))
                self.assertEqual(db.jobs_needing_enrichment(only_missing=True), [])
                self.assertEqual(len(db.jobs_needing_enrichment(only_missing=False)), 1)
                stats = db.enrichment_stats()
                self.assertEqual((stats["enriched"], stats["hidden"], stats["pending"]), (1, 1, 0))
                db.delete_jobs([j.id])
                self.assertIsNone(db.get_enrichment(j.id))
            finally:
                db.close()

    def test_scoring_query_carries_enrichment_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = JobDB(db_path=Path(tmp) / "jobs.db")
            try:
                j = _job(); db.insert_job(j)
                db.upsert_enrichment(j.id, {"en_resolved_work_mode": "hybrid", "en_ncr_match": 0, "en_location_ok": 0})
                rows = db.get_jobs_for_scoring()
                self.assertEqual(rows[0]["en_resolved_work_mode"], "hybrid")
                self.assertEqual(rows[0]["title"], j.title)   # jobs columns not shadowed
            finally:
                db.close()


class ApiVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        warnings.simplefilter("ignore", DeprecationWarning)
        from fastapi.testclient import TestClient

        import api.server as server

        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "jobs.db"
        db = JobDB(db_path=path)
        try:
            self.ok = _job(location="Gurugram, India", apply_link="https://acme.example/jobs/ok")
            self.hidden = _job(title="Product Owner", location="India (Hybrid)", apply_link="https://acme.example/jobs/hidden")
            self.mnc_bad_listing = _job(title="Product Lead", location="Bengaluru", apply_link="https://acme.example/jobs/blr")
            for j in (self.ok, self.hidden, self.mnc_bad_listing):
                db.insert_job(j)
            db.upsert_enrichment(self.hidden.id, {"en_resolved_locations": "Bangalore, Karnataka, IN", "en_resolved_work_mode": "hybrid",
                                                  "en_location_ok": 0, "en_resolution_source": "structured",
                                                  "en_location_reason": "hybrid in Bangalore (job page) — not NCR",
                                                  "en_locations_json": [{"city": "Bangalore", "region": "Karnataka", "country": "IN"}]})
            # an enrichment row can also rescue a listing the filter rejects
            db.upsert_enrichment(self.mnc_bad_listing.id, {"en_resolved_locations": "Gurgaon, IN", "en_location_ok": 1,
                                                           "en_resolution_source": "structured", "en_resolved_work_mode": "onsite"})
        finally:
            db.close()
        patcher = mock.patch.object(server, "_jobs_db", lambda: JobDB(db_path=path)); patcher.start(); self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)

    def test_strict_hides_resolved_rejects_and_rescues_resolved_passes(self) -> None:
        d = self.client.get("/api/jobs").json()
        ids = {j["id"] for j in d["jobs"]}
        self.assertIn(self.ok.id, ids)
        self.assertIn(self.mnc_bad_listing.id, ids)      # listing said Bengaluru, job page said Gurgaon
        self.assertNotIn(self.hidden.id, ids)
        self.assertEqual(d["hidden_count"], 1)
        shown = self.client.get("/api/jobs?location_mode=all").json()
        self.assertEqual(shown["total"], 3)
        hidden = next(j for j in shown["jobs"] if j["id"] == self.hidden.id)
        self.assertEqual((hidden["location_display"], hidden["location_source"], hidden["location_ok"], hidden["work_mode"]),
                         ("Bangalore, Karnataka, IN", "structured", False, "hybrid"))
        mnc = self.client.get("/api/mnc-jobs").json()
        self.assertEqual(mnc["total"], 2)
        self.assertEqual(mnc["hidden_count"], 1)

    def test_tracked_filter_hides_end_of_cycle_rows(self) -> None:
        self.client.post(f"/api/jobs/{self.ok.id}/status", json={"status": "skipped"})
        d = self.client.get("/api/jobs").json()
        self.assertNotIn(self.ok.id, {j["id"] for j in d["jobs"]})
        self.assertEqual(d["hidden_by_status"], 1)
        self.assertEqual(self.client.get("/api/jobs?tracked=skipped").json()["total"], 1)
        self.assertEqual(self.client.get("/api/jobs?tracked=all").json()["total"], 2)
        self.client.post(f"/api/jobs/{self.ok.id}/status", json={"status": "shortlisted"})
        self.assertIn(self.ok.id, {j["id"] for j in self.client.get("/api/jobs").json()["jobs"]})   # saved stays active

    def test_detail_endpoint_carries_enrichment(self) -> None:
        j = self.client.get(f"/api/jobs/{self.hidden.id}").json()
        self.assertEqual(j["enrichment"]["locations"][0]["city"], "Bangalore")
        self.assertEqual(j["location_reason"], "hybrid in Bangalore (job page) — not NCR")
        stats = self.client.get("/api/enrichment/stats").json()
        self.assertEqual((stats["enriched"], stats["hidden"]), (2, 1))


class LLMVerifierTests(unittest.TestCase):
    def test_invented_cities_and_country_names_are_dropped(self) -> None:
        text = build_input("PM", "Acme", "India", "Based in our Gurgaon office. Nokia has offices in Finland and Germany.", [], max_chars=3000)
        clean, dropped = verify({"cities": ["Pune", "Gurgaon", "Finland"], "countries": ["India", "Japan"], "work_mode": "onsite",
                                 "remote_scope": "unknown", "seniority": "senior", "role_type": "product_manager",
                                 "years_min": 5, "years_max": 3, "evidence_location": "Based in our Gurgaon office.",
                                 "evidence_work_mode": "not in text"}, text)
        self.assertEqual(clean["cities"], ["Gurgaon"])
        self.assertEqual(clean["countries"], ["India"])
        self.assertIn("city:Pune", dropped)
        self.assertIn("city:Finland(country)", dropped)
        self.assertIn("country:Japan", dropped)
        self.assertEqual((clean["years_min"], clean["years_max"]), (5, None))
        self.assertEqual(clean["evidence_work_mode"], "")

    def test_single_city_needs_supporting_evidence(self) -> None:
        text = build_input("PM", "Acme", "India", "We have offices in Bangalore. This role is remote within India.", [], max_chars=3000)
        clean, dropped = verify({"cities": ["Bangalore"], "countries": [], "work_mode": "remote", "remote_scope": "india",
                                 "seniority": "unknown", "role_type": "other", "years_min": None, "years_max": None,
                                 "evidence_location": "This role is remote within India.", "evidence_work_mode": "This role is remote within India."}, text)
        self.assertEqual(clean["cities"], [])
        self.assertIn("city:Bangalore(evidence)", dropped)

    def test_placeholder_descriptions(self) -> None:
        self.assertTrue(is_placeholder_description("Direct from Acme careers page"))
        self.assertTrue(is_placeholder_description(""))
        self.assertFalse(is_placeholder_description("We are hiring a Senior Product Manager to own the payments roadmap in Gurgaon."))


if __name__ == "__main__":
    unittest.main()
