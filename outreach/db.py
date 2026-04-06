from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from outreach.models import OutreachContact, OutreachEmail


class OutreachDB:
    """SQLite store for outreach contacts and emails."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent / "output" / "outreach.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS outreach_contacts (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                company_domain TEXT,
                contact_name TEXT,
                contact_title TEXT,
                contact_email TEXT,
                contact_email_status TEXT,
                contact_linkedin TEXT,
                contact_role_type TEXT,
                source TEXT,
                source_job_id TEXT,
                source_job_title TEXT,
                source_job_link TEXT,
                funding_amount TEXT,
                funding_series TEXT,
                funding_date TEXT,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'new'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_company_email
                ON outreach_contacts(company, contact_email)
                WHERE contact_email != '' AND contact_email IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_contacts_company ON outreach_contacts(company);
            CREATE INDEX IF NOT EXISTS idx_contacts_status ON outreach_contacts(status);

            CREATE TABLE IF NOT EXISTS outreach_emails (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                sequence_step INTEGER DEFAULT 1,
                subject TEXT,
                body_html TEXT,
                body_plain TEXT,
                template_name TEXT,
                scheduled_send_at TEXT,
                actual_sent_at TEXT,
                status TEXT DEFAULT 'draft',
                gmail_message_id TEXT,
                gmail_thread_id TEXT,
                FOREIGN KEY(contact_id) REFERENCES outreach_contacts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_emails_status ON outreach_emails(status);
            CREATE INDEX IF NOT EXISTS idx_emails_contact ON outreach_emails(contact_id);
            CREATE INDEX IF NOT EXISTS idx_emails_scheduled ON outreach_emails(scheduled_send_at);

            CREATE TABLE IF NOT EXISTS outreach_credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                credits_used INTEGER DEFAULT 1,
                timestamp TEXT NOT NULL
            );
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def company_has_outreach(self, company: str) -> bool:
        """Check if we already have an active outreach for this company."""
        row = self.conn.execute(
            "SELECT 1 FROM outreach_contacts WHERE LOWER(company) = LOWER(?) AND status NOT IN ('skipped')",
            (company,),
        ).fetchone()
        return row is not None

    def insert_contact(self, contact: OutreachContact) -> bool:
        """Insert a contact. Returns True if inserted, False if duplicate."""
        try:
            self.conn.execute(
                """INSERT INTO outreach_contacts
                   (id, company, company_domain, contact_name, contact_title,
                    contact_email, contact_email_status, contact_linkedin,
                    contact_role_type, source, source_job_id, source_job_title,
                    source_job_link, funding_amount, funding_series, funding_date,
                    created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contact.id, contact.company, contact.company_domain,
                    contact.contact_name, contact.contact_title,
                    contact.contact_email, contact.contact_email_status,
                    contact.contact_linkedin, contact.contact_role_type,
                    contact.source, contact.source_job_id, contact.source_job_title,
                    contact.source_job_link, contact.funding_amount,
                    contact.funding_series, contact.funding_date,
                    contact.created_at.isoformat(), contact.status,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_contact_status(self, contact_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE outreach_contacts SET status = ? WHERE id = ?",
            (status, contact_id),
        )
        self.conn.commit()

    def update_contact_email(self, contact_id: str, email: str, email_status: str) -> None:
        self.conn.execute(
            "UPDATE outreach_contacts SET contact_email = ?, contact_email_status = ?, status = 'enriched' WHERE id = ?",
            (email, email_status, contact_id),
        )
        self.conn.commit()

    def get_contacts_by_status(self, status: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM outreach_contacts WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contact(self, contact_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM outreach_contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_contacts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM outreach_contacts ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Emails
    # ------------------------------------------------------------------

    def insert_email(self, email: OutreachEmail) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO outreach_emails
                   (id, contact_id, sequence_step, subject, body_html, body_plain,
                    template_name, scheduled_send_at, actual_sent_at, status,
                    gmail_message_id, gmail_thread_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    email.id, email.contact_id, email.sequence_step,
                    email.subject, email.body_html, email.body_plain,
                    email.template_name,
                    email.scheduled_send_at.isoformat() if email.scheduled_send_at else None,
                    email.actual_sent_at.isoformat() if email.actual_sent_at else None,
                    email.status, email.gmail_message_id, email.gmail_thread_id,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_email_status(self, email_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE outreach_emails SET status = ? WHERE id = ?",
            (status, email_id),
        )
        self.conn.commit()

    def update_email_content(self, email_id: str, subject: str, body_plain: str, body_html: str) -> None:
        self.conn.execute(
            "UPDATE outreach_emails SET subject = ?, body_plain = ?, body_html = ? WHERE id = ?",
            (subject, body_plain, body_html, email_id),
        )
        self.conn.commit()

    def mark_email_sent(self, email_id: str, gmail_message_id: str, gmail_thread_id: str) -> None:
        self.conn.execute(
            """UPDATE outreach_emails
               SET status = 'sent', actual_sent_at = ?, gmail_message_id = ?, gmail_thread_id = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), gmail_message_id, gmail_thread_id, email_id),
        )
        self.conn.commit()

    def get_draft_emails(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT e.*, c.company, c.contact_name, c.contact_email, c.contact_title,
                      c.source, c.funding_amount, c.funding_series
               FROM outreach_emails e
               JOIN outreach_contacts c ON e.contact_id = c.id
               WHERE e.status = 'draft'
               ORDER BY e.scheduled_send_at ASC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_approved_emails(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT e.*, c.company, c.contact_name, c.contact_email, c.contact_title
               FROM outreach_emails e
               JOIN outreach_contacts c ON e.contact_id = c.id
               WHERE e.status = 'approved'
               ORDER BY e.scheduled_send_at ASC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_sendable_emails(self) -> list[dict]:
        """Get approved emails whose scheduled_send_at has passed (or is NULL)."""
        now = datetime.now().isoformat()
        rows = self.conn.execute(
            """SELECT e.*, c.company, c.contact_name, c.contact_email, c.contact_title
               FROM outreach_emails e
               JOIN outreach_contacts c ON e.contact_id = c.id
               WHERE e.status = 'approved'
                     AND (e.scheduled_send_at IS NULL OR e.scheduled_send_at <= ?)
               ORDER BY e.scheduled_send_at ASC""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contact_id_for_email(self, email_id: str) -> str | None:
        """Look up the contact_id for a given email."""
        row = self.conn.execute(
            "SELECT contact_id FROM outreach_emails WHERE id = ?", (email_id,)
        ).fetchone()
        return row[0] if row else None

    def all_emails_terminal_for_contact(self, contact_id: str) -> bool:
        """Check if all emails for a contact are in a terminal state (skipped/snoozed/sent/bounced/replied)."""
        row = self.conn.execute(
            """SELECT COUNT(*) FROM outreach_emails
               WHERE contact_id = ? AND status IN ('draft', 'approved')""",
            (contact_id,),
        ).fetchone()
        return row[0] == 0

    def get_due_followups(self) -> list[dict]:
        """Get follow-up emails that are due (scheduled_send_at <= now) and still draft."""
        now = datetime.now().isoformat()
        rows = self.conn.execute(
            """SELECT e.*, c.company, c.contact_name, c.contact_email, c.contact_title
               FROM outreach_emails e
               JOIN outreach_contacts c ON e.contact_id = c.id
               WHERE e.status = 'draft' AND e.sequence_step > 1
                     AND e.scheduled_send_at <= ?
               ORDER BY e.scheduled_send_at ASC""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def cancel_pending_followups(self, contact_id: str) -> int:
        """Cancel all unsent follow-ups for a contact. Returns count cancelled."""
        cursor = self.conn.execute(
            """UPDATE outreach_emails SET status = 'skipped'
               WHERE contact_id = ? AND status IN ('draft', 'approved') AND sequence_step > 1""",
            (contact_id,),
        )
        self.conn.commit()
        return cursor.rowcount

    def get_today_send_count(self) -> int:
        today = datetime.now().date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) FROM outreach_emails WHERE status = 'sent' AND actual_sent_at >= ?",
            (today,),
        ).fetchone()
        return row[0] if row else 0

    def get_thread_id_for_contact(self, contact_id: str) -> str:
        """Get the Gmail thread ID from the first sent email to this contact."""
        row = self.conn.execute(
            """SELECT gmail_thread_id FROM outreach_emails
               WHERE contact_id = ? AND status = 'sent' AND gmail_thread_id != ''
               ORDER BY sequence_step ASC LIMIT 1""",
            (contact_id,),
        ).fetchone()
        return row[0] if row else ""

    # ------------------------------------------------------------------
    # Credits tracking
    # ------------------------------------------------------------------

    def log_credit(self, provider: str, operation: str, credits: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO outreach_credits (provider, operation, credits_used, timestamp) VALUES (?, ?, ?, ?)",
            (provider, operation, credits, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_monthly_credits(self, provider: str) -> int:
        month_start = datetime.now().replace(day=1).isoformat()
        row = self.conn.execute(
            "SELECT COALESCE(SUM(credits_used), 0) FROM outreach_credits WHERE provider = ? AND timestamp >= ?",
            (provider, month_start),
        ).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        stats = {}
        for status in ["new", "enriched", "queued", "approved", "sent", "replied", "bounced", "skipped", "snoozed"]:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM outreach_contacts WHERE status = ?", (status,)
            ).fetchone()
            stats[f"contacts_{status}"] = row[0]

        for status in ["draft", "approved", "sent", "bounced", "replied", "skipped", "snoozed"]:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM outreach_emails WHERE status = ?", (status,)
            ).fetchone()
            stats[f"emails_{status}"] = row[0]

        stats["today_sent"] = self.get_today_send_count()
        stats["apollo_credits_this_month"] = self.get_monthly_credits("apollo")
        stats["prospeo_credits_this_month"] = self.get_monthly_credits("prospeo")
        return stats

    def close(self) -> None:
        self.conn.close()
