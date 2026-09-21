from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.job import Job
from services.title_filter import is_relevant_title


# ─── Canonical application status vocabulary ──────────────────────────────────
# Used by BOTH the CLI (main.py) and the API (api/server.py). Any place that
# validates status should import APPLICATION_STATUSES from here so we never
# end up with two divergent vocabularies again.
APPLICATION_STATUSES: frozenset[str] = frozenset({
    "to_review",     # initial state (not yet triaged)
    "shortlisted",   # saved to tracker, not yet applied
    "reached_out",   # outreach message sent, no application yet
    "applied",       # application submitted
    "screening",     # recruiter screen scheduled or in progress
    "interview",     # interview stage (any round)
    "offer",         # offer received
    "rejected",      # rejected by company or withdrawn
    "parked",        # deprioritised, revisit later
    "skipped",       # user skipped / not interested
})

# Statuses that should set applied_at when first entered
STATUSES_COUNTING_AS_APPLIED: frozenset[str] = frozenset({
    "applied", "screening", "interview", "offer",
})


def application_id_for(job_id: str) -> str:
    """Deterministic application ID for a given job_id.

    Single source of truth — both CLI (main.py shortlist) and API
    (api/server.py) call this so a single job never ends up with two
    application rows under different IDs.
    """
    return hashlib.sha256(f"app|{job_id}".encode()).hexdigest()[:16]


class JobDB:
    """SQLite-backed store for scraped job listings, run metadata, and scoring."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent / "output" / "jobs.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        # `main.py enrich` commits per job for up to an hour while the dashboard reads:
        # wait instead of raising "database is locked".
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._init_tables()
        self._migrate_columns()
        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

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
                dedup_hash TEXT,
                -- scoring columns (added via migration if missing)
                priority_score INTEGER DEFAULT 0,
                relevance_score INTEGER DEFAULT 0,
                salary_likelihood_score INTEGER DEFAULT 0,
                warmth_score INTEGER DEFAULT 0,
                company_quality_score INTEGER DEFAULT 0,
                semantic_score INTEGER DEFAULT 0,
                priority_bucket TEXT DEFAULT '',
                score_reasons TEXT DEFAULT '[]',
                priority_flags TEXT DEFAULT '[]'
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

            -- Per-company outcome of a source run (MNC careers today). One row per
            -- company per batch; batch_id groups one CLI invocation. Kept separate
            -- from `runs` so ~350 rows never hijack "last run" (main.py status,
            -- /api/stats read runs ORDER BY run_id DESC).
            CREATE TABLE IF NOT EXISTS source_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                source TEXT NOT NULL,
                company TEXT NOT NULL,
                ats_type TEXT DEFAULT '',
                lane TEXT DEFAULT '',
                status TEXT NOT NULL,
                fetched INTEGER DEFAULT 0,
                total_reported INTEGER,
                pages INTEGER DEFAULT 0,
                cap_hit INTEGER DEFAULT 0,
                matched INTEGER DEFAULT 0,
                inserted INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                strategy TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_source_runs_lookup ON source_runs(source, company, timestamp);

            -- Per-job enrichment: the structured detail record behind a listing (Oracle/Workday
            -- API, JSON-LD, microdata), the local-LLM extraction, and the *resolved* location
            -- the filters/scoring/dashboard use. All columns are en_-prefixed so a
            -- `LEFT JOIN ... SELECT *` never shadows a jobs column. jobs.location itself is
            -- never rewritten (dedup_hash depends on it).
            CREATE TABLE IF NOT EXISTS job_enrichment (
                job_id TEXT PRIMARY KEY,
                en_detail_source TEXT DEFAULT '',
                en_detail_url TEXT DEFAULT '',
                en_detail_status TEXT DEFAULT '',
                en_detail_fetched_at TEXT,
                en_locations_json TEXT DEFAULT '[]',
                en_workplace_type TEXT DEFAULT '',
                en_description_full TEXT DEFAULT '',
                en_posted_date TEXT DEFAULT '',
                en_employment_type TEXT DEFAULT '',
                en_llm_model TEXT DEFAULT '',
                en_llm_status TEXT DEFAULT '',
                en_llm_json TEXT DEFAULT '',
                en_remote_scope TEXT DEFAULT '',
                en_resolved_locations TEXT DEFAULT '',
                en_resolved_country TEXT DEFAULT '',
                en_resolved_work_mode TEXT DEFAULT '',
                en_ncr_match INTEGER,
                en_location_ok INTEGER,
                en_resolution_source TEXT DEFAULT '',
                en_location_reason TEXT DEFAULT '',
                en_seniority TEXT DEFAULT '',
                en_role_type TEXT DEFAULT '',
                en_years_min INTEGER,
                en_years_max INTEGER,
                en_enriched_at TEXT,
                en_description_hash TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_enrichment_ok ON job_enrichment(en_location_ok);

            CREATE TABLE IF NOT EXISTS company_profiles (
                normalized_company TEXT PRIMARY KEY,
                company_display_name TEXT,
                company_domain TEXT,
                is_mnc INTEGER DEFAULT 0,
                is_funded INTEGER DEFAULT 0,
                funding_series TEXT,
                funding_amount TEXT,
                funding_date TEXT,
                pm_open_roles_count INTEGER DEFAULT 0,
                seen_platforms TEXT DEFAULT '[]',
                careers_page TEXT,
                hq_location TEXT,
                is_yc_backed INTEGER DEFAULT 0,
                yc_batch TEXT DEFAULT '',
                last_refreshed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                company TEXT,
                title TEXT,
                status TEXT DEFAULT 'to_review',
                applied_at TEXT,
                resume_version TEXT,
                cover_letter_path TEXT,
                outreach_email_id TEXT,
                referral_contact TEXT,
                next_followup_at TEXT,
                last_action_at TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
            CREATE INDEX IF NOT EXISTS idx_app_job_id ON applications(job_id);

            CREATE TABLE IF NOT EXISTS network_contacts (
                id TEXT PRIMARY KEY,
                full_name TEXT,
                company TEXT,
                title TEXT,
                location TEXT,
                education TEXT,
                linkedin_url TEXT,
                source TEXT,
                connection_degree TEXT,
                is_alumni INTEGER DEFAULT 0,
                is_iit_top7 INTEGER DEFAULT 0,
                raw_data TEXT,
                imported_at TEXT
            );

            CREATE TABLE IF NOT EXISTS job_connection_matches (
                job_id TEXT,
                company TEXT,
                match_type TEXT,
                contact_name TEXT,
                contact_title TEXT,
                match_score INTEGER,
                notes TEXT,
                PRIMARY KEY (job_id, contact_name)
            );
            CREATE INDEX IF NOT EXISTS idx_jcm_job ON job_connection_matches(job_id);
            CREATE INDEX IF NOT EXISTS idx_jcm_company ON job_connection_matches(company);

            -- ── YC Startups ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS yc_companies (
                id TEXT PRIMARY KEY,
                company_slug TEXT UNIQUE NOT NULL,
                company_name TEXT NOT NULL,
                description TEXT DEFAULT '',
                long_description TEXT DEFAULT '',
                batch TEXT DEFAULT '',
                website TEXT DEFAULT '',
                hq_location TEXT DEFAULT '',
                team_size TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                subindustry TEXT DEFAULT '',
                status TEXT DEFAULT 'Active',
                logo_url TEXT DEFAULT '',
                founders TEXT DEFAULT '[]',
                is_hiring INTEGER DEFAULT 0,
                is_hiring_pm INTEGER DEFAULT 0,
                hiring_url TEXT DEFAULT '',
                latest_hiring_check_at TEXT,
                last_refreshed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_yc_batch ON yc_companies(batch);
            CREATE INDEX IF NOT EXISTS idx_yc_hiring ON yc_companies(is_hiring);
            CREATE INDEX IF NOT EXISTS idx_yc_hiring_pm ON yc_companies(is_hiring_pm);
            CREATE INDEX IF NOT EXISTS idx_yc_slug ON yc_companies(company_slug);

            CREATE TABLE IF NOT EXISTS yc_hiring_signals (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_source TEXT DEFAULT '',
                signal_date TEXT DEFAULT '',
                signal_detail TEXT DEFAULT '',
                checked_at TEXT,
                FOREIGN KEY(company_id) REFERENCES yc_companies(id)
            );
            CREATE INDEX IF NOT EXISTS idx_yc_sig_company ON yc_hiring_signals(company_id);

            CREATE TABLE IF NOT EXISTS yc_founder_contacts (
                id TEXT PRIMARY KEY,
                yc_company_id TEXT NOT NULL,
                founder_name TEXT NOT NULL,
                founder_title TEXT DEFAULT '',
                founder_email TEXT DEFAULT '',
                founder_email_verified INTEGER DEFAULT 0,
                founder_linkedin TEXT DEFAULT '',
                founder_twitter TEXT DEFAULT '',
                enrichment_source TEXT DEFAULT '',
                enriched_at TEXT,
                FOREIGN KEY(yc_company_id) REFERENCES yc_companies(id)
            );
            CREATE INDEX IF NOT EXISTS idx_yc_fc_company ON yc_founder_contacts(yc_company_id);
        """)
        self.conn.commit()

    def _migrate_columns(self) -> None:
        """Add scoring columns to pre-existing jobs tables (idempotent)."""
        new_cols = [
            ("priority_score", "INTEGER DEFAULT 0"),
            ("relevance_score", "INTEGER DEFAULT 0"),
            ("salary_likelihood_score", "INTEGER DEFAULT 0"),
            ("warmth_score", "INTEGER DEFAULT 0"),
            ("company_quality_score", "INTEGER DEFAULT 0"),
            ("semantic_score", "INTEGER DEFAULT 0"),
            ("priority_bucket", "TEXT DEFAULT ''"),
            ("score_reasons", "TEXT DEFAULT '[]'"),
            ("priority_flags", "TEXT DEFAULT '[]'"),
        ]
        existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for col_name, col_ddl in new_cols:
            if col_name not in existing:
                self.conn.execute(
                    f"ALTER TABLE jobs ADD COLUMN {col_name} {col_ddl}"
                )

        # Migrate company_profiles for YC columns
        cp_cols = [
            ("is_yc_backed", "INTEGER DEFAULT 0"),
            ("yc_batch", "TEXT DEFAULT ''"),
            ("hq_country", "TEXT DEFAULT ''"),  # from mnc_careers/data/mnc_input.csv via company_intel
        ]
        cp_existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(company_profiles)").fetchall()
        }
        for col_name, col_ddl in cp_cols:
            if col_name not in cp_existing:
                self.conn.execute(
                    f"ALTER TABLE company_profiles ADD COLUMN {col_name} {col_ddl}"
                )

        # Migrate yc_companies for Indian-origin founder classification columns
        yc_new_cols = [
            ("has_indian_origin_founder", "INTEGER DEFAULT 0"),
            ("indian_origin_confidence", "REAL DEFAULT 0.0"),
        ]
        yc_existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(yc_companies)").fetchall()
        }
        for col_name, col_ddl in yc_new_cols:
            if col_name not in yc_existing:
                self.conn.execute(
                    f"ALTER TABLE yc_companies ADD COLUMN {col_name} {col_ddl}"
                )
        self.conn.commit()

    def _ensure_indexes(self) -> None:
        """Create indexes only after migrations so older DBs open cleanly."""
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_priority_score ON jobs(priority_score)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Job operations
    # ------------------------------------------------------------------

    def job_exists(self, job_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None

    def insert_job(self, job: Job) -> bool:
        """Insert a job if it doesn't already exist. Returns True if inserted.

        Silently rejects jobs whose title fails the configured title filter —
        see services/title_filter.py for the single source of truth.
        """
        if not is_relevant_title(job.title):
            return False
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

    def find_irrelevant_title_ids(self) -> list[str]:
        """IDs of jobs whose title fails the (config-driven) title filter.

        Evaluated in Python via services.title_filter so the rule lives in
        exactly one place (a SQL LIKE would silently drift from it). Jobs with
        an applications row are excluded so tracked applications survive.
        """
        rows = self.conn.execute(
            """SELECT id, title FROM jobs
               WHERE id NOT IN (SELECT job_id FROM applications WHERE job_id IS NOT NULL)"""
        ).fetchall()
        return [r["id"] for r in rows if not is_relevant_title(r["title"])]

    def find_irrelevant_location_ids(self) -> list[str]:
        """IDs of jobs whose location fails services.location_filter (jobs with applications excluded)."""
        from services.location_filter import is_acceptable_location

        rows = self.conn.execute(
            """SELECT id, location FROM jobs
               WHERE id NOT IN (SELECT job_id FROM applications WHERE job_id IS NOT NULL)"""
        ).fetchall()
        return [r["id"] for r in rows if not is_acceptable_location(r["location"] or "")]

    def delete_jobs(self, ids: list[str]) -> int:
        """Delete jobs (and their connection matches) by id. Returns the count deleted."""
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM job_connection_matches WHERE job_id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM job_enrichment WHERE job_id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids)

    def purge_irrelevant_titles(self) -> int:
        """Delete existing jobs whose title fails the title filter.

        Skips any job that has a row in the applications table (shortlisted,
        applied, etc.) so tracked applications are never silently removed.
        Returns the count of deleted rows.
        """
        ids = self.find_irrelevant_title_ids()
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(
            f"DELETE FROM job_connection_matches WHERE job_id IN ({placeholders})", ids
        )
        self.conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids)

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
    # Scoring methods
    # ------------------------------------------------------------------

    def get_job_by_id(self, job_id: str) -> Optional[dict]:
        """Return a single job dict by ID, or None if not found."""
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_jobs_for_scoring(self, rescore_all: bool = False) -> list[dict]:
        """Return jobs that need (re)scoring.

        A job is considered unscored when priority_bucket is empty ('').
        We deliberately do NOT use priority_score = 0 as the condition because
        a legitimately poor-signal job can score 0 and should not be rescored
        on every call.
        """
        if rescore_all:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE is_duplicate = 0 ORDER BY scraped_at DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE is_duplicate = 0 AND priority_bucket = '' ORDER BY scraped_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_job_warmth_score(self, job_id: str, warmth: int) -> None:
        """Update only the warmth_score for a single job (called by connection_matcher)."""
        self.conn.execute(
            "UPDATE jobs SET warmth_score = ? WHERE id = ?",
            (warmth, job_id),
        )
        # Caller is responsible for commit (batch updates use this)

    def update_job_scores(self, job_id: str, scores: dict) -> None:
        """Persist scoring results for a single job."""
        self.conn.execute(
            """UPDATE jobs SET
                priority_score = ?,
                relevance_score = ?,
                salary_likelihood_score = ?,
                warmth_score = ?,
                company_quality_score = ?,
                semantic_score = ?,
                priority_bucket = ?,
                score_reasons = ?,
                priority_flags = ?
               WHERE id = ?""",
            (
                scores.get("priority_score", 0),
                scores.get("relevance_score", 0),
                scores.get("salary_likelihood_score", 0),
                scores.get("warmth_score", 0),
                scores.get("company_quality_score", 0),
                scores.get("semantic_score", 0),
                scores.get("priority_bucket", ""),
                scores.get("score_reasons", "[]"),
                scores.get("priority_flags", "[]"),
                job_id,
            ),
        )
        self.conn.commit()

    def get_top_recommended_jobs(
        self,
        top_n: int = 25,
        min_score: int = 0,
        bucket: Optional[str] = None,
        platform: Optional[str] = None,
        remote_only: bool = False,
        include_low: bool = False,
    ) -> list[dict]:
        """Return top-ranked jobs with optional filters."""
        conditions = ["is_duplicate = 0"]
        params: list = []

        if min_score > 0:
            conditions.append("priority_score >= ?")
            params.append(min_score)

        if bucket:
            conditions.append("priority_bucket = ?")
            params.append(bucket)
        elif not include_low:
            # Exclude both 'low' AND '' (unscored). priority_bucket = '' is the
            # sentinel for never-scored jobs; they shouldn't be treated as
            # recommendable until the scorer has actually run on them.
            conditions.append("priority_bucket NOT IN ('low', '')")

        if platform:
            conditions.append("platform = ?")
            params.append(platform)

        if remote_only:
            conditions.append("LOWER(location) LIKE '%remote%'")

        where = " AND ".join(conditions)
        params.append(top_n)

        rows = self.conn.execute(
            f"""SELECT * FROM jobs
                WHERE {where}
                ORDER BY priority_score DESC, scraped_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Application tracker
    # ------------------------------------------------------------------

    def upsert_application(self, app: dict) -> None:
        """Insert or update an application row.

        Uses COALESCE so that calling this with ``applied_at=None`` on an
        existing row does NOT wipe out a previously-recorded apply
        timestamp. Same for notes / referral / cover letter — they are
        only overwritten when the caller explicitly provides a new value.
        """
        self.conn.execute(
            """INSERT INTO applications
               (id, job_id, company, title, status, applied_at, resume_version,
                cover_letter_path, outreach_email_id, referral_contact,
                next_followup_at, last_action_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                applied_at = COALESCE(excluded.applied_at, applications.applied_at),
                resume_version = COALESCE(excluded.resume_version, applications.resume_version),
                cover_letter_path = COALESCE(excluded.cover_letter_path, applications.cover_letter_path),
                outreach_email_id = COALESCE(excluded.outreach_email_id, applications.outreach_email_id),
                referral_contact = COALESCE(excluded.referral_contact, applications.referral_contact),
                next_followup_at = COALESCE(excluded.next_followup_at, applications.next_followup_at),
                last_action_at = COALESCE(excluded.last_action_at, applications.last_action_at),
                notes = COALESCE(excluded.notes, applications.notes)""",
            (
                app["id"], app.get("job_id"), app.get("company"), app.get("title"),
                app.get("status", "to_review"), app.get("applied_at"),
                app.get("resume_version"), app.get("cover_letter_path"),
                app.get("outreach_email_id"), app.get("referral_contact"),
                app.get("next_followup_at"), app.get("last_action_at"),
                app.get("notes"),
            ),
        )
        self.conn.commit()

    def get_applications(self, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY last_action_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM applications ORDER BY last_action_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_application_status(self, job_id: str, status: str, notes: Optional[str] = None) -> bool:
        now = datetime.now().isoformat()
        result = self.conn.execute(
            """UPDATE applications
               SET status = ?, last_action_at = ?, notes = COALESCE(?, notes)
               WHERE job_id = ?""",
            (status, now, notes, job_id),
        )
        self.conn.commit()
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Company profiles
    # ------------------------------------------------------------------

    def upsert_company_profile(self, profile: dict) -> None:
        self.conn.execute(
            """INSERT INTO company_profiles
               (normalized_company, company_display_name, company_domain,
                is_mnc, is_funded, funding_series, funding_amount, funding_date,
                pm_open_roles_count, seen_platforms, careers_page, hq_location,
                is_yc_backed, yc_batch, hq_country, last_refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(normalized_company) DO UPDATE SET
                company_display_name = excluded.company_display_name,
                company_domain = excluded.company_domain,
                is_mnc = excluded.is_mnc,
                is_funded = excluded.is_funded,
                funding_series = excluded.funding_series,
                funding_amount = excluded.funding_amount,
                funding_date = excluded.funding_date,
                pm_open_roles_count = excluded.pm_open_roles_count,
                seen_platforms = excluded.seen_platforms,
                careers_page = excluded.careers_page,
                hq_location = excluded.hq_location,
                is_yc_backed = MAX(excluded.is_yc_backed, company_profiles.is_yc_backed),
                yc_batch = COALESCE(excluded.yc_batch, company_profiles.yc_batch),
                hq_country = COALESCE(NULLIF(excluded.hq_country, ''), company_profiles.hq_country),
                last_refreshed_at = excluded.last_refreshed_at""",
            (
                profile["normalized_company"],
                profile.get("company_display_name"),
                profile.get("company_domain"),
                int(profile.get("is_mnc", 0)),
                int(profile.get("is_funded", 0)),
                profile.get("funding_series"),
                profile.get("funding_amount"),
                profile.get("funding_date"),
                profile.get("pm_open_roles_count", 0),
                json.dumps(profile.get("seen_platforms") or []),
                profile.get("careers_page"),
                profile.get("hq_location"),
                int(profile.get("is_yc_backed", 0)),
                profile.get("yc_batch", ""),
                profile.get("hq_country", "") or "",
                profile.get("last_refreshed_at", datetime.now().isoformat()),
            ),
        )
        self.conn.commit()

    def get_all_company_profiles(self) -> dict[str, dict]:
        """Return mapping normalized_company -> profile dict."""
        rows = self.conn.execute("SELECT * FROM company_profiles").fetchall()
        result = {}
        for row in rows:
            d = dict(row)
            d["seen_platforms"] = json.loads(d.get("seen_platforms") or "[]")
            result[d["normalized_company"]] = d
        return result

    def get_company_profile(self, normalized_company: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM company_profiles WHERE normalized_company = ?",
            (normalized_company,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["seen_platforms"] = json.loads(d.get("seen_platforms") or "[]")
        return d

    # ------------------------------------------------------------------
    # Network contacts
    # ------------------------------------------------------------------

    def upsert_network_contact(self, contact: dict) -> None:
        self.conn.execute(
            """INSERT INTO network_contacts
               (id, full_name, company, title, location, education,
                linkedin_url, source, connection_degree, is_alumni,
                is_iit_top7, raw_data, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                company = excluded.company,
                title = excluded.title,
                education = excluded.education,
                connection_degree = excluded.connection_degree,
                is_alumni = excluded.is_alumni,
                is_iit_top7 = excluded.is_iit_top7""",
            (
                contact["id"],
                contact.get("full_name"),
                contact.get("company"),
                contact.get("title"),
                contact.get("location"),
                contact.get("education"),
                contact.get("linkedin_url"),
                contact.get("source"),
                contact.get("connection_degree"),
                int(contact.get("is_alumni", 0)),
                int(contact.get("is_iit_top7", 0)),
                contact.get("raw_data"),
                contact.get("imported_at", datetime.now().isoformat()),
            ),
        )
        self.conn.commit()

    def get_network_contacts(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM network_contacts").fetchall()
        return [dict(r) for r in rows]

    def get_contacts_for_company(self, company_slug: str) -> list[dict]:
        """Return contacts whose normalised company slug contains or equals company_slug.

        Matching is done in Python (not SQL) for consistency with the normalisation
        logic in services/scoring._company_slug().
        """
        from services.scoring import _company_slug

        all_contacts = self.get_network_contacts()
        result = []
        for c in all_contacts:
            slug = _company_slug(c.get("company", ""))
            if slug and (slug == company_slug or company_slug in slug or slug in company_slug):
                result.append(c)
        return result

    def upsert_job_connection_match(self, match: dict) -> None:
        self.conn.execute(
            """INSERT INTO job_connection_matches
               (job_id, company, match_type, contact_name, contact_title, match_score, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_id, contact_name) DO UPDATE SET
                match_type = excluded.match_type,
                match_score = excluded.match_score,
                notes = excluded.notes""",
            (
                match["job_id"], match.get("company"), match.get("match_type"),
                match.get("contact_name"), match.get("contact_title"),
                match.get("match_score", 0), match.get("notes"),
            ),
        )
        self.conn.commit()

    def get_connection_matches_for_job(self, job_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM job_connection_matches WHERE job_id = ? ORDER BY match_score DESC",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

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

    # ------------------------------------------------------------------
    # job_enrichment — structured detail + LLM extraction + resolved location
    # ------------------------------------------------------------------

    ENRICHMENT_COLUMNS = (
        "en_detail_source", "en_detail_url", "en_detail_status", "en_detail_fetched_at", "en_locations_json",
        "en_workplace_type", "en_description_full", "en_posted_date", "en_employment_type",
        "en_llm_model", "en_llm_status", "en_llm_json", "en_remote_scope",
        "en_resolved_locations", "en_resolved_country", "en_resolved_work_mode", "en_ncr_match", "en_location_ok",
        "en_resolution_source", "en_location_reason", "en_seniority", "en_role_type", "en_years_min", "en_years_max",
        "en_enriched_at", "en_description_hash",
    )

    def upsert_enrichment(self, job_id: str, row: dict) -> None:
        """Insert or update one job's enrichment. Only the keys present in `row` are written
        on update (COALESCE-free: an explicit None clears a value), so the structured pass
        and the later LLM pass can each write their own columns."""
        cols = [c for c in self.ENRICHMENT_COLUMNS if c in row]
        if not cols:
            return
        values = [json.dumps(row[c]) if isinstance(row[c], (list, dict)) else row[c] for c in cols]
        assignments = ", ".join(f"{c} = excluded.{c}" for c in cols)
        self.conn.execute(
            f"""INSERT INTO job_enrichment (job_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})
                ON CONFLICT(job_id) DO UPDATE SET {assignments}""",
            [job_id, *values],
        )
        self.conn.commit()

    def get_enrichment(self, job_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM job_enrichment WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_enrichment_many(self, job_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(job_ids), 500):
            chunk = job_ids[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            for r in self.conn.execute(f"SELECT * FROM job_enrichment WHERE job_id IN ({placeholders})", chunk).fetchall():
                out[r["job_id"]] = dict(r)
        return out

    def jobs_needing_enrichment(self, *, only_missing: bool = True, limit: Optional[int] = None,
                                platform: Optional[str] = None, job_ids: Optional[list[str]] = None) -> list[dict]:
        """Non-duplicate jobs with no enrichment row (or all, for a backfill), newest first."""
        where = ["j.is_duplicate = 0"]
        params: list = []
        if only_missing:
            where.append("e.job_id IS NULL")
        if platform:
            where.append("j.platform LIKE ?")
            params.append(platform if "%" in platform else platform)
        if job_ids:
            where.append(f"j.id IN ({','.join('?' * len(job_ids))})")
            params.extend(job_ids)
        sql = f"""SELECT j.* FROM jobs j LEFT JOIN job_enrichment e ON e.job_id = j.id
                  WHERE {' AND '.join(where)} ORDER BY j.scraped_at DESC"""
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def enrichment_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE is_duplicate = 0").fetchone()[0]
        rows = self.conn.execute(
            """SELECT e.en_resolution_source AS src, e.en_location_ok AS ok, COUNT(*) AS n
               FROM job_enrichment e JOIN jobs j ON j.id = e.job_id WHERE j.is_duplicate = 0
               GROUP BY 1, 2"""
        ).fetchall()
        by_source: dict[str, int] = {}
        hidden = 0
        enriched = 0
        for r in rows:
            by_source[r["src"] or ""] = by_source.get(r["src"] or "", 0) + r["n"]
            enriched += r["n"]
            if r["ok"] == 0:
                hidden += r["n"]
        llm = self.conn.execute(
            "SELECT en_llm_status, COUNT(*) FROM job_enrichment WHERE en_llm_status != '' GROUP BY 1"
        ).fetchall()
        return {
            "total_jobs": total, "enriched": enriched, "pending": max(total - enriched, 0),
            "hidden": hidden, "by_source": by_source, "llm": {r[0]: r[1] for r in llm},
        }

    # ------------------------------------------------------------------
    # source_runs — per-company diagnostics for MNC/VC style sources
    # ------------------------------------------------------------------
    def save_source_runs(self, source: str, rows: list[dict], batch_id: str) -> None:
        """Bulk-insert per-company outcomes (one executemany, one commit)."""
        if not rows:
            return
        now = datetime.now().isoformat()
        self.conn.executemany(
            """INSERT INTO source_runs (batch_id, source, company, ats_type, lane, status,
               fetched, total_reported, pages, cap_hit, matched, inserted, error, strategy,
               duration_ms, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    batch_id, source, r.get("name") or r.get("company", ""), r.get("ats", r.get("ats_type", "")),
                    r.get("lane", ""), r.get("status", ""), int(r.get("fetched", 0) or 0), r.get("total_reported"),
                    int(r.get("pages", 0) or 0), int(bool(r.get("cap_hit"))), int(r.get("matched", 0) or 0),
                    int(r.get("inserted", 0) or 0), (r.get("error") or "")[:500], (r.get("strategy") or "")[:200],
                    int(r.get("duration_ms", 0) or 0), now,
                )
                for r in rows
            ],
        )
        self.conn.commit()

    def get_latest_source_runs(self, source: str) -> dict[str, dict]:
        """Latest row per company for *source* (keyed by company name)."""
        rows = self.conn.execute(
            """SELECT sr.* FROM source_runs sr
               JOIN (SELECT company, MAX(id) AS max_id FROM source_runs WHERE source = ? GROUP BY company) latest
                 ON latest.max_id = sr.id
               WHERE sr.source = ?""",
            (source, source),
        ).fetchall()
        return {r["company"]: dict(r) for r in rows}

    def get_source_run_batches(self, source: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            """SELECT batch_id, MIN(timestamp) AS timestamp, COUNT(*) AS companies,
                      SUM(status = 'ok') AS ok, SUM(status = 'empty') AS empty, SUM(status = 'failed') AS failed,
                      SUM(matched) AS matched, SUM(inserted) AS inserted
               FROM source_runs WHERE source = ? GROUP BY batch_id ORDER BY MIN(id) DESC LIMIT ?""",
            (source, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_run(self) -> Optional[dict]:
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
    # Analytics
    # ------------------------------------------------------------------

    def get_pipeline_stats(self) -> dict:
        stats: dict = {}
        stats["total_jobs"] = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_duplicate = 0"
        ).fetchone()[0]
        stats["scored_jobs"] = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_duplicate = 0 AND priority_bucket != ''"
        ).fetchone()[0]
        for bucket in ("must_apply", "high", "medium", "low"):
            stats[f"bucket_{bucket}"] = self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_duplicate = 0 AND priority_bucket = ?",
                (bucket,),
            ).fetchone()[0]
        stats["total_applications"] = self.conn.execute(
            "SELECT COUNT(*) FROM applications"
        ).fetchone()[0]
        by_status = self.conn.execute(
            "SELECT status, COUNT(*) FROM applications GROUP BY status"
        ).fetchall()
        stats["applications_by_status"] = {r[0]: r[1] for r in by_status}
        stats["network_contacts"] = self.conn.execute(
            "SELECT COUNT(*) FROM network_contacts"
        ).fetchone()[0]
        stats["company_profiles"] = self.conn.execute(
            "SELECT COUNT(*) FROM company_profiles"
        ).fetchone()[0]
        return stats

    def get_source_quality_stats(self, *, rollup_direct: bool = True) -> list[dict]:
        """Per-source quality stats.

        With ``rollup_direct`` (default) the hundreds of per-company
        ``mnc_*`` / ``vc_*`` platforms collapse into two rows, ``mnc_careers``
        and ``vc_portals``, so analytics stays readable; ``companies`` carries
        how many distinct portals contributed.
        """
        group = (
            """CASE WHEN platform LIKE 'mnc\_%' ESCAPE '\\' THEN 'mnc_careers'
                    WHEN platform LIKE 'vc\_%' ESCAPE '\\' THEN 'vc_portals'
                    ELSE platform END"""
            if rollup_direct else "platform"
        )
        rows = self.conn.execute(
            f"""SELECT {group} AS platform,
                       COUNT(*) AS total,
                       COUNT(DISTINCT platform) AS companies,
                       AVG(priority_score) AS avg_score,
                       SUM(CASE WHEN priority_bucket IN ('must_apply','high') THEN 1 ELSE 0 END) AS high_quality
                FROM jobs WHERE is_duplicate = 0
                GROUP BY {group} ORDER BY avg_score DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # YC Startups
    # ------------------------------------------------------------------

    def upsert_yc_company(self, company: dict) -> None:
        """Insert or update a YC company."""
        self.conn.execute(
            """INSERT INTO yc_companies
               (id, company_slug, company_name, description, long_description,
                batch, website, hq_location, team_size, industry, subindustry,
                status, logo_url, founders, is_hiring, is_hiring_pm, hiring_url,
                latest_hiring_check_at, last_refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                company_name = excluded.company_name,
                description = COALESCE(excluded.description, yc_companies.description),
                long_description = COALESCE(excluded.long_description, yc_companies.long_description),
                batch = COALESCE(excluded.batch, yc_companies.batch),
                website = COALESCE(excluded.website, yc_companies.website),
                hq_location = COALESCE(excluded.hq_location, yc_companies.hq_location),
                team_size = COALESCE(excluded.team_size, yc_companies.team_size),
                industry = COALESCE(excluded.industry, yc_companies.industry),
                subindustry = COALESCE(excluded.subindustry, yc_companies.subindustry),
                status = COALESCE(excluded.status, yc_companies.status),
                logo_url = COALESCE(excluded.logo_url, yc_companies.logo_url),
                founders = COALESCE(excluded.founders, yc_companies.founders),
                is_hiring = excluded.is_hiring,
                last_refreshed_at = excluded.last_refreshed_at""",
            (
                company["id"], company["company_slug"], company["company_name"],
                company.get("description", ""), company.get("long_description", ""),
                company.get("batch", ""), company.get("website", ""),
                company.get("hq_location", ""), company.get("team_size", ""),
                company.get("industry", ""), company.get("subindustry", ""),
                company.get("status", "Active"), company.get("logo_url", ""),
                json.dumps(company.get("founders") or []),
                int(company.get("is_hiring", 0)),
                int(company.get("is_hiring_pm", 0)),
                company.get("hiring_url", ""),
                company.get("latest_hiring_check_at"),
                company.get("last_refreshed_at", datetime.now().isoformat()),
            ),
        )
        # Caller should commit after batch

    def upsert_yc_companies(self, companies: list[dict]) -> int:
        """Bulk upsert YC companies. Returns count inserted/updated."""
        for c in companies:
            self.upsert_yc_company(c)
        self.conn.commit()
        return len(companies)

    def _build_yc_conditions(
        self,
        batch: Optional[str] = None,
        hiring_only: bool = False,
        hiring_pm_only: bool = False,
        indian_founders_only: bool = False,
        locations: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        team_size_min: int = 0,
        search: str = "",
    ) -> tuple[list[str], list]:
        """Build WHERE conditions for YC company queries (shared by get/count)."""
        conditions: list[str] = []
        params: list = []

        if batch:
            conditions.append("batch = ?")
            params.append(batch)
        if hiring_only:
            conditions.append("is_hiring = 1")
        if hiring_pm_only:
            conditions.append("is_hiring_pm = 1")
        if indian_founders_only:
            conditions.append("has_indian_origin_founder = 1")
        if locations:
            placeholders = ", ".join("?" * len(locations))
            conditions.append(f"hq_location IN ({placeholders})")
            params.extend(locations)
        if industries:
            placeholders = ", ".join("?" * len(industries))
            conditions.append(f"industry IN ({placeholders})")
            params.extend(industries)
        if team_size_min > 0:
            conditions.append("team_size != '' AND CAST(team_size AS INTEGER) >= ?")
            params.append(team_size_min)
        if search:
            conditions.append(
                "(company_name LIKE ? OR description LIKE ? OR industry LIKE ? OR hq_location LIKE ?)"
            )
            term = f"%{search}%"
            params.extend([term, term, term, term])

        return conditions, params

    def get_yc_companies(
        self,
        batch: Optional[str] = None,
        hiring_only: bool = False,
        hiring_pm_only: bool = False,
        indian_founders_only: bool = False,
        locations: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        team_size_min: int = 0,
        search: str = "",
        limit: int = 0,
        offset: int = 0,
    ) -> list[dict]:
        """Query YC companies with filters."""
        conditions, params = self._build_yc_conditions(
            batch=batch, hiring_only=hiring_only, hiring_pm_only=hiring_pm_only,
            indian_founders_only=indian_founders_only, locations=locations,
            industries=industries, team_size_min=team_size_min, search=search,
        )
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM yc_companies {where} ORDER BY batch DESC, company_name ASC"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
            if offset > 0:
                sql += " OFFSET ?"
                params.append(offset)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._yc_row_to_dict(r) for r in rows]

    def get_yc_company_by_id(self, company_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM yc_companies WHERE id = ?", (company_id,)
        ).fetchone()
        return self._yc_row_to_dict(row) if row else None

    def update_yc_hiring_status(
        self, company_id: str, is_hiring_pm: bool, hiring_url: str = "",
    ) -> None:
        """Mark a YC company as hiring for PM roles."""
        self.conn.execute(
            """UPDATE yc_companies
               SET is_hiring_pm = ?, hiring_url = ?, latest_hiring_check_at = ?
               WHERE id = ?""",
            (int(is_hiring_pm), hiring_url, datetime.now().isoformat(), company_id),
        )
        # Caller commits after batch

    def upsert_yc_hiring_signal(self, signal: dict) -> None:
        self.conn.execute(
            """INSERT INTO yc_hiring_signals
               (id, company_id, signal_type, signal_source, signal_date,
                signal_detail, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                signal_detail = excluded.signal_detail,
                checked_at = excluded.checked_at""",
            (
                signal["id"], signal["company_id"], signal["signal_type"],
                signal.get("signal_source", ""), signal.get("signal_date", ""),
                signal.get("signal_detail", ""), signal.get("checked_at", ""),
            ),
        )

    def get_yc_hiring_signals(self, company_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM yc_hiring_signals WHERE company_id = ? ORDER BY checked_at DESC",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_yc_founder_contact(self, contact: dict) -> None:
        self.conn.execute(
            """INSERT INTO yc_founder_contacts
               (id, yc_company_id, founder_name, founder_title, founder_email,
                founder_email_verified, founder_linkedin, founder_twitter,
                enrichment_source, enriched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                founder_title = COALESCE(excluded.founder_title, yc_founder_contacts.founder_title),
                founder_email = COALESCE(excluded.founder_email, yc_founder_contacts.founder_email),
                founder_email_verified = excluded.founder_email_verified,
                founder_linkedin = COALESCE(excluded.founder_linkedin, yc_founder_contacts.founder_linkedin),
                founder_twitter = COALESCE(excluded.founder_twitter, yc_founder_contacts.founder_twitter),
                enrichment_source = excluded.enrichment_source,
                enriched_at = excluded.enriched_at""",
            (
                contact["id"], contact["yc_company_id"], contact["founder_name"],
                contact.get("founder_title", ""), contact.get("founder_email", ""),
                int(contact.get("founder_email_verified", 0)),
                contact.get("founder_linkedin", ""), contact.get("founder_twitter", ""),
                contact.get("enrichment_source", ""),
                contact.get("enriched_at", datetime.now().isoformat()),
            ),
        )

    def get_yc_founder_contacts(self, company_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM yc_founder_contacts WHERE yc_company_id = ? ORDER BY founder_name",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_yc_all_founder_contacts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT fc.*, yc.company_name, yc.batch FROM yc_founder_contacts fc "
            "JOIN yc_companies yc ON fc.yc_company_id = yc.id "
            "ORDER BY yc.batch DESC, yc.company_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_yc_founders_filtered(
        self,
        batch: Optional[str] = None,
        hiring_only: bool = False,
        hiring_pm_only: bool = False,
        indian_founders_only: bool = False,
        locations: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        team_size_min: int = 0,
        search: str = "",
    ) -> list[dict]:
        """Query YC founder contacts filtered by company-level criteria."""
        conditions, params = self._build_yc_conditions(
            batch=batch, hiring_only=hiring_only, hiring_pm_only=hiring_pm_only,
            indian_founders_only=indian_founders_only, locations=locations,
            industries=industries, team_size_min=team_size_min, search=search,
        )
        if conditions:
            sub_where = f"WHERE {' AND '.join(conditions)}"
            full_where = f"WHERE fc.yc_company_id IN (SELECT id FROM yc_companies {sub_where})"
        else:
            full_where = ""
        sql = (
            f"SELECT fc.founder_name, fc.founder_linkedin, fc.founder_title, "
            f"fc.yc_company_id, yc.company_name, yc.batch, yc.company_slug "
            f"FROM yc_founder_contacts fc "
            f"JOIN yc_companies yc ON fc.yc_company_id = yc.id "
            f"{full_where} "
            f"ORDER BY yc.batch DESC, yc.company_name, fc.founder_name"
        )
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_yc_stats(self) -> dict:
        """Return aggregate YC stats for the dashboard."""
        stats: dict = {}
        stats["total_companies"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_companies"
        ).fetchone()[0]
        stats["active_companies"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_companies WHERE status = 'Active'"
        ).fetchone()[0]
        stats["hiring_companies"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_companies WHERE is_hiring = 1"
        ).fetchone()[0]
        stats["hiring_pm"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_companies WHERE is_hiring_pm = 1"
        ).fetchone()[0]
        stats["total_founders"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_founder_contacts"
        ).fetchone()[0]
        stats["verified_emails"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_founder_contacts WHERE founder_email_verified = 1"
        ).fetchone()[0]
        stats["total_signals"] = self.conn.execute(
            "SELECT COUNT(*) FROM yc_hiring_signals"
        ).fetchone()[0]
        # Batch distribution (top 10 batches)
        batch_rows = self.conn.execute(
            "SELECT batch, COUNT(*) as cnt FROM yc_companies "
            "WHERE batch != '' GROUP BY batch ORDER BY batch DESC LIMIT 10"
        ).fetchall()
        stats["top_batches"] = [{"batch": r[0], "count": r[1]} for r in batch_rows]
        return stats

    def get_yc_batches(self) -> list[str]:
        """Return all distinct YC batches in reverse-chronological order.

        Sorts by year descending, then by season within each year:
        Winter > Spring > Summer > Fall  (calendar order within a year).
        """
        import re as _re
        _SEASON_ORDER = {"W": 0, "Sp": 1, "S": 2, "F": 3}

        rows = self.conn.execute(
            "SELECT DISTINCT batch FROM yc_companies WHERE batch != ''"
        ).fetchall()
        batches = [r[0] for r in rows]

        def _sort_key(b: str) -> tuple:
            m = _re.match(r"([A-Za-z]+)(\d+)", b)
            if not m:
                return (0, 0)
            season, year_str = m.group(1), m.group(2)
            year = int(year_str)
            return (-year, _SEASON_ORDER.get(season, 9))

        batches.sort(key=_sort_key)
        return batches

    def count_yc_companies(
        self,
        batch: Optional[str] = None,
        hiring_only: bool = False,
        hiring_pm_only: bool = False,
        indian_founders_only: bool = False,
        locations: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        team_size_min: int = 0,
        search: str = "",
    ) -> int:
        conditions, params = self._build_yc_conditions(
            batch=batch, hiring_only=hiring_only, hiring_pm_only=hiring_pm_only,
            indian_founders_only=indian_founders_only, locations=locations,
            industries=industries, team_size_min=team_size_min, search=search,
        )
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return self.conn.execute(
            f"SELECT COUNT(*) FROM yc_companies {where}", params
        ).fetchone()[0]

    def update_yc_indian_origin(
        self, company_id: str, has_indian: bool, confidence: float,
    ) -> None:
        """Update the Indian-origin founder classification for a company."""
        self.conn.execute(
            """UPDATE yc_companies
               SET has_indian_origin_founder = ?, indian_origin_confidence = ?
               WHERE id = ?""",
            (int(has_indian), confidence, company_id),
        )
        # Caller commits after batch

    def get_yc_locations(self, limit: int = 100) -> list[str]:
        """Return distinct non-empty hq_location values, most common first."""
        rows = self.conn.execute(
            """SELECT hq_location, COUNT(*) as cnt FROM yc_companies
               WHERE hq_location != ''
               GROUP BY hq_location ORDER BY cnt DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_yc_industries(self) -> list[str]:
        """Return distinct non-empty industry values, most common first."""
        rows = self.conn.execute(
            """SELECT industry, COUNT(*) as cnt FROM yc_companies
               WHERE industry != ''
               GROUP BY industry ORDER BY cnt DESC""",
        ).fetchall()
        return [r[0] for r in rows]

    def _yc_row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["founders"] = json.loads(d.get("founders") or "[]")
        d["is_hiring"] = bool(d.get("is_hiring"))
        d["is_hiring_pm"] = bool(d.get("is_hiring_pm"))
        d["has_indian_origin_founder"] = bool(d.get("has_indian_origin_founder", False))
        d.setdefault("indian_origin_confidence", 0.0)
        return d

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["skills"] = json.loads(d.get("skills") or "[]")
        d["is_duplicate"] = bool(d.get("is_duplicate"))
        # Ensure score fields are present with defaults
        d.setdefault("priority_score", 0)
        d.setdefault("priority_bucket", "")
        d.setdefault("score_reasons", "[]")
        d.setdefault("priority_flags", "[]")
        return d

    def close(self) -> None:
        self.conn.close()
