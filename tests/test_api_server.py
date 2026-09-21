from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from models.job import Job
from storage.db import JobDB


class JobDetailEndpointTests(unittest.TestCase):
    """Regression: ISSUE-002 — the tracker's job detail modal reads title_category /
    work_mode from GET /api/jobs/{id}, which only the list endpoint used to decorate.
    Found by /qa on 2026-09-21
    Report: .gstack/qa-reports/qa-report-localhost-8000-2026-09-21.md"""

    def setUp(self) -> None:
        warnings.simplefilter("ignore", DeprecationWarning)
        from fastapi.testclient import TestClient

        import api.server as server

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = Path(self.tmp.name) / "jobs.db"
        db = JobDB(db_path=db_path)
        try:
            self.job = Job(title="Senior Product Manager", company="Acme", location="Gurugram (Hybrid)",
                           platform="naukri", apply_link="https://acme.example/jobs/1", description="Hybrid role")
            db.insert_job(self.job)
        finally:
            db.close()
        patcher = mock.patch.object(server, "_jobs_db", lambda: JobDB(db_path=db_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)

    def test_detail_is_decorated_like_the_list(self) -> None:
        r = self.client.get(f"/api/jobs/{self.job.id}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["title_category"], "product_manager")
        self.assertEqual(body["work_mode"], "hybrid")
        self.assertEqual(body["apply_link"], "https://acme.example/jobs/1")
        self.assertIsNone(body["application"])

    def test_skipped_status_round_trip_is_visible_in_detail(self) -> None:
        # ISSUE-001: skipped is a real application status the tracker must be able to read back
        r = self.client.post(f"/api/jobs/{self.job.id}/status", json={"status": "skipped"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{self.job.id}").json()["application"]["status"], "skipped")
        apps = self.client.get("/api/applications").json()
        self.assertEqual([a["status"] for a in apps], ["skipped"])
        self.assertEqual(apps[0]["job"]["id"], self.job.id)
        # untrack removes it entirely (the modal's Untrack button)
        self.assertEqual(self.client.delete(f"/api/jobs/{self.job.id}/shortlist").status_code, 200)
        self.assertEqual(self.client.get("/api/applications").json(), [])

    def test_unknown_job_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/jobs/doesnotexist").status_code, 404)


if __name__ == "__main__":
    unittest.main()
