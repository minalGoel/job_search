from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from models.job import Job


class JobDB:
    """SQLite-backed store for scraped job listings and run metadata."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent / "output" / "jobs.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
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
            CREATE INDEX IF NOT EXISTS idx_dedup_hash ON jobs(dedup_hash);
            CREATE INDEX IF NOT EXISTS idx_platform ON jobs(platform);
            CREATE INDEX IF NOT EXISTS idx_scraped_at ON jobs(scraped_at);

            CREATE TABLE IF NOT EXISTS runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                platforms_scraped TEXT DEFAULT '[]',
                new_count INTEGER DEFAULT 0,
                duplicate_count INTEGER DEFAULT 0,
                errors TEXT DEFAULT '{}'
            );
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Job operations
    # ------------------------------------------------------------------

    def job_exists(self, job_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None

    def insert_job(self, job: Job) -> bool:
        """Insert a job if it doesn't already exist. Returns True if inserted."""
        if self.job_exists(job.id):
            return False
        self.conn.execute(
            """INSERT INTO jobs (id, platform, title, company, location, salary,
               posted_date, skills, description, apply_link, scraped_at,
               is_duplicate, duplicate_of, dedup_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id, job.platform, job.title, job.company, job.location,
                job.salary,
                job.posted_date.isoformat() if job.posted_date else None,
                json.dumps(job.skills), job.description, job.apply_link,
                job.scraped_at.isoformat(), int(job.is_duplicate),
                job.duplicate_of, job.dedup_hash,
            ),
        )
        self.conn.commit()
        return True

    def insert_jobs(self, jobs: list[Job]) -> tuple[int, int]:
        """Bulk insert. Returns (inserted_count, skipped_count)."""
        inserted = skipped = 0
        for job in jobs:
            if self.insert_job(job):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def get_jobs_by_dedup_hash(self, dedup_hash: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE dedup_hash = ?", (dedup_hash,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_duplicate(self, job_id: str, duplicate_of: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET is_duplicate = 1, duplicate_of = ? WHERE id = ?",
            (duplicate_of, job_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Run metadata
    # ------------------------------------------------------------------

    def save_run(
        self,
        platforms: list[str],
        new_count: int,
        dup_count: int,
        errors: dict,
    ) -> None:
        self.conn.execute(
            """INSERT INTO runs (timestamp, platforms_scraped, new_count,
               duplicate_count, errors) VALUES (?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(),
                json.dumps(platforms),
                new_count,
                dup_count,
                json.dumps(errors),
            ),
        )
        self.conn.commit()

    def get_last_run(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["platforms_scraped"] = json.loads(d["platforms_scraped"] or "[]")
        except json.JSONDecodeError:
            d["platforms_scraped"] = []
        try:
            d["errors"] = json.loads(d["errors"] or "{}")
        except json.JSONDecodeError:
            d["errors"] = {}
        return d

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all_jobs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY scraped_at DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_new_jobs(self, since: datetime) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE scraped_at >= ? ORDER BY scraped_at DESC",
            (since.isoformat(),),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["skills"] = json.loads(d.get("skills") or "[]")
        d["is_duplicate"] = bool(d.get("is_duplicate"))
        return d

    def close(self) -> None:
        self.conn.close()
