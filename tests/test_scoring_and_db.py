from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.scoring import score_job
from storage.db import JobDB


class JobDBMigrationTests(unittest.TestCase):
    def test_opening_old_jobs_db_runs_migration_before_index_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "jobs.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    salary TEXT,
                    posted_date TEXT,
                    skills TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    apply_link TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    is_duplicate INTEGER DEFAULT 0,
                    duplicate_of TEXT,
                    dedup_hash TEXT
                );
                CREATE INDEX idx_dedup_hash ON jobs(dedup_hash);
                CREATE INDEX idx_platform ON jobs(platform);
                CREATE INDEX idx_scraped_at ON jobs(scraped_at);
                """
            )
            conn.commit()
            conn.close()

            db = JobDB(db_path=db_path)
            try:
                columns = {
                    row[1]
                    for row in db.conn.execute("PRAGMA table_info(jobs)").fetchall()
                }
                self.assertIn("priority_score", columns)

                indexes = {
                    row[1]
                    for row in db.conn.execute("PRAGMA index_list(jobs)").fetchall()
                }
                self.assertIn("idx_priority_score", indexes)
            finally:
                db.close()


class ScoringTests(unittest.TestCase):
    def test_associate_pm_is_demoted(self) -> None:
        scored = score_job(
            {
                "title": "Associate Product Manager",
                "description": "",
                "location": "Delhi NCR",
                "platform": "linkedin",
                "company": "Example",
                "posted_date": None,
                "warmth_score": 0,
            }
        )

        self.assertEqual(scored["priority_bucket"], "low")
        self.assertIn("associate_product_manager", scored["priority_flags"])
        self.assertNotIn("product_manager", scored["score_reasons"])

    def test_short_high_paying_company_names_do_not_match_by_substring(self) -> None:
        false_positive = score_job(
            {
                "title": "Senior Product Manager",
                "description": "",
                "location": "Delhi NCR",
                "platform": "linkedin",
                "company": "Publicis Sapient",
                "posted_date": None,
                "warmth_score": 0,
            }
        )
        exact_match = score_job(
            {
                "title": "Senior Product Manager",
                "description": "",
                "location": "Delhi NCR",
                "platform": "linkedin",
                "company": "SAP",
                "posted_date": None,
                "warmth_score": 0,
            }
        )

        self.assertNotIn("high_paying_company", false_positive["score_reasons"])
        self.assertIn("high_paying_company", exact_match["score_reasons"])


if __name__ == "__main__":
    unittest.main()
