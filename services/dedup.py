from __future__ import annotations

import structlog

from models.job import Job
from storage.db import JobDB

log = structlog.get_logger(__name__)


def mark_cross_platform_duplicates(new_jobs: list[Job], db: JobDB) -> int:
    """Check new jobs against existing DB entries for cross-platform duplicates.

    Marks duplicates in-place on the Job objects AND in the database.
    Returns the number of duplicates found.
    """
    dup_count = 0

    for job in new_jobs:
        existing = db.get_jobs_by_dedup_hash(job.dedup_hash)
        # Filter to jobs from OTHER platforms
        cross = [e for e in existing if e["platform"] != job.platform and e["id"] != job.id]
        if cross:
            # The earliest-scraped job is the canonical one
            canonical = min(cross, key=lambda e: e["scraped_at"])
            job.is_duplicate = True
            job.duplicate_of = canonical["id"]
            db.mark_duplicate(job.id, canonical["id"])
            dup_count += 1
            log.info(
                "dedup.cross_platform",
                job_id=job.id,
                platform=job.platform,
                duplicate_of=canonical["id"],
                canonical_platform=canonical["platform"],
                company=job.company,
            )

    return dup_count
