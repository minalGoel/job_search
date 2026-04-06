from __future__ import annotations

"""
Connection / Alumni Matcher (P0.5)

Imports LinkedIn connection CSV exports into network_contacts table,
then matches contacts against scraped jobs to produce a warmth score.

CSV import supports two formats:
  1. LinkedIn "Connections" export (First Name, Last Name, Email Address,
     Company, Position, Connected On, URL)
  2. Custom curated CSV with columns: full_name, company, title, location,
     education, linkedin_url, connection_degree
"""

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config.scoring_rules import IIT_TOP7_KEYWORDS

if TYPE_CHECKING:
    from storage.db import JobDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _company_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", _normalize(name))
    suffixes = {
        "pvt", "ltd", "limited", "private", "inc", "incorporated",
        "corp", "corporation", "llc", "technologies", "technology",
        "software", "solutions", "india", "services", "labs",
    }
    words = [w for w in s.split() if w not in suffixes]
    return " ".join(words).strip()


def _contact_id(full_name: str, company: str, linkedin_url: str) -> str:
    raw = f"{_normalize(full_name)}|{_company_slug(company)}|{_normalize(linkedin_url)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _is_iit_top7(education: str) -> bool:
    edu_lower = _normalize(education)
    return any(kw in edu_lower for kw in IIT_TOP7_KEYWORDS)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def import_connections_csv(csv_path: Path, db: "JobDB", alumni_colleges: list[str] | None = None) -> int:
    """
    Parse a LinkedIn or custom connections CSV and upsert into network_contacts.
    Returns the number of contacts imported.
    """
    alumni_colleges = [_normalize(c) for c in (alumni_colleges or [])]
    imported = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]

        # Detect format
        is_linkedin_format = "first name" in fieldnames or "first_name" in fieldnames

        for raw_row in reader:
            row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}

            if is_linkedin_format:
                first = row.get("first name") or row.get("first_name", "")
                last = row.get("last name") or row.get("last_name", "")
                full_name = f"{first} {last}".strip()
                company = row.get("company", "")
                title = row.get("position", "")
                linkedin_url = row.get("url", "") or row.get("linkedin_url", "")
                education = row.get("education", "")
                location = row.get("location", "")
                degree = "1st"  # LinkedIn export = 1st connections
            else:
                full_name = row.get("full_name", "")
                company = row.get("company", "")
                title = row.get("title", "")
                linkedin_url = row.get("linkedin_url", "")
                education = row.get("education", "")
                location = row.get("location", "")
                degree = row.get("connection_degree", "1st")

            if not full_name:
                continue

            is_alumni = int(any(college in _normalize(education) for college in alumni_colleges))
            is_iit = int(_is_iit_top7(education))

            contact = {
                "id": _contact_id(full_name, company, linkedin_url),
                "full_name": full_name,
                "company": company,
                "title": title,
                "location": location,
                "education": education,
                "linkedin_url": linkedin_url,
                "source": "linkedin_export",
                "connection_degree": degree,
                "is_alumni": is_alumni,
                "is_iit_top7": is_iit,
                "raw_data": str(row),
                "imported_at": datetime.now().isoformat(),
            }
            db.upsert_network_contact(contact)
            imported += 1

    return imported


# ---------------------------------------------------------------------------
# Warmth scoring
# ---------------------------------------------------------------------------

# Warmth score contributions
WARMTH_SCORES = {
    "direct_connection": 40,
    "alumni": 20,
    "iit_top7": 15,
    "second_degree": 10,
}


def match_connections_to_jobs(db: "JobDB") -> int:
    """
    For every non-duplicate job, find matching network contacts at the
    same company and write job_connection_matches rows.

    Updates warmth_score on jobs in the DB.
    Returns the number of jobs updated with warmth > 0.
    """
    contacts = db.get_network_contacts()
    if not contacts:
        return 0

    # Build lookup: company_slug -> list[contact]
    by_company: dict[str, list[dict]] = {}
    for c in contacts:
        slug = _company_slug(c.get("company", ""))
        if slug:
            by_company.setdefault(slug, []).append(c)

    jobs = db.get_all_jobs()
    updated = 0

    for job in jobs:
        if job.get("is_duplicate"):
            continue

        job_company_slug = _company_slug(job.get("company", ""))
        matched = by_company.get(job_company_slug, [])

        if not matched:
            # Try substring match for compound company names
            for slug, contacts_at_co in by_company.items():
                if slug and (slug in job_company_slug or job_company_slug in slug):
                    matched = contacts_at_co
                    break

        if not matched:
            continue

        best_warmth = 0
        for contact in matched:
            degree = (contact.get("connection_degree") or "").strip()
            w = 0
            if degree in ("1st", "1"):
                w += WARMTH_SCORES["direct_connection"]
            elif degree in ("2nd", "2"):
                w += WARMTH_SCORES["second_degree"]

            if contact.get("is_alumni"):
                w += WARMTH_SCORES["alumni"]
            if contact.get("is_iit_top7"):
                w += WARMTH_SCORES["iit_top7"]

            w = min(w, 100)

            # Persist the match row
            db.upsert_job_connection_match({
                "job_id": job["id"],
                "company": job.get("company"),
                "match_type": "direct" if degree in ("1st", "1") else "indirect",
                "contact_name": contact.get("full_name"),
                "contact_title": contact.get("title"),
                "match_score": w,
                "notes": f"degree={degree}, alumni={contact.get('is_alumni')}, iit={contact.get('is_iit_top7')}",
            })

            best_warmth = max(best_warmth, w)

        if best_warmth > 0:
            # Update warmth_score on the job; re-scoring will incorporate it
            db.conn.execute(
                "UPDATE jobs SET warmth_score = ? WHERE id = ?",
                (best_warmth, job["id"]),
            )
            updated += 1

    db.conn.commit()
    return updated
