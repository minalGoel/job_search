from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
import typer

from config.settings import Settings
from config.search_params import SearchParams
from models.job import Job

# Ensure project root is on sys.path so absolute imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

log = structlog.get_logger(__name__)
app = typer.Typer(help="Job Search Aggregator — scrape PM roles across 9+ platforms, track funding, scan VC & MNC portals")

settings = Settings()
params = SearchParams()


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def _run_all(platforms: list[str] | None = None) -> None:
    """Execute a full scrape → dedup → export → notify cycle."""
    from browser.context import BrowserManager
    from scrapers import SCRAPER_REGISTRY
    from storage.db import JobDB
    from services.dedup import mark_cross_platform_duplicates
    from services.exporter import export_csv, export_excel
    from services.notifier import send_new_jobs_alert
    from services.location_filter import is_acceptable_location, explain as explain_location

    run_start = datetime.now()
    db = JobDB()
    try:
        target_platforms = platforms or list(SCRAPER_REGISTRY.keys())
        errors: dict[str, str] = {}
        all_new_jobs: list[Job] = []

        async with BrowserManager() as bm:
            # Run all scrapers concurrently
            tasks = {}
            for name in target_platforms:
                if name not in SCRAPER_REGISTRY:
                    typer.echo(f"Unknown platform: {name}", err=True)
                    continue
                scraper_cls = SCRAPER_REGISTRY[name]
                scraper = scraper_cls(bm, params)
                tasks[name] = asyncio.create_task(scraper._safe_scrape())

            for name, task in tasks.items():
                try:
                    jobs, scrape_error = await task
                    if scrape_error:
                        errors[name] = scrape_error
                        typer.echo(f"  {name}: ERROR — {scrape_error}", err=True)
                        # Still process any jobs that came back before the failure
                    if jobs:
                        inserted_jobs: list[Job] = []
                        skipped = 0
                        location_rejected = 0
                        for job in jobs:
                            # Pipeline-level location gate: defense in depth.
                            # Individual scrapers already filter, but this catches
                            # anything that slipped through (e.g. Naukri returning
                            # a Mumbai job in a Delhi search, LinkedIn cross-border).
                            if not is_acceptable_location(job.location):
                                location_rejected += 1
                                log.debug("pipeline.location_rejected",
                                          platform=name,
                                          title=job.title,
                                          company=job.company,
                                          location=job.location,
                                          reason=explain_location(job.location))
                                continue
                            if db.insert_job(job):
                                inserted_jobs.append(job)
                            else:
                                skipped += 1

                        all_new_jobs.extend(inserted_jobs)
                        loc_note = f", {location_rejected} wrong-location" if location_rejected else ""
                        typer.echo(f"  {name}: {len(inserted_jobs)} new, {skipped} existing{loc_note}")
                    elif not scrape_error:
                        typer.echo(f"  {name}: 0 results")
                except Exception as e:
                    # Safety net: _safe_scrape should catch everything, but
                    # fall through here if the task wrapper itself crashes.
                    errors[name] = f"{type(e).__name__}: {e}"
                    typer.echo(f"  {name}: ERROR — {e}", err=True)

        # Dedup across platforms
        dup_count = mark_cross_platform_duplicates(all_new_jobs, db)

        # Export
        settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        all_jobs = db.get_all_jobs()
        new_jobs_dicts = db.get_new_jobs(run_start)

        csv_path = export_csv(new_jobs_dicts, settings.OUTPUT_DIR)
        export_excel(all_jobs, new_jobs_dicts, settings.OUTPUT_DIR)

        # Save run metadata
        db.save_run(target_platforms, len(all_new_jobs), dup_count, errors)

        # Notify
        if new_jobs_dicts:
            send_new_jobs_alert(new_jobs_dicts, settings, csv_path)

        typer.echo(
            f"\nDone: {len(all_new_jobs)} new jobs, {dup_count} cross-platform duplicates, "
            f"{len(errors)} platform errors."
        )
    finally:
        db.close()


@app.command()
def run(
    platform: Optional[list[str]] = typer.Option(
        None, "--platform", "-p", help="Specific platform(s) to scrape"
    ),
) -> None:
    """Run scrapers once and export results."""
    _configure_logging()
    typer.echo("Starting job search scan...\n")
    asyncio.run(_run_all(platform))


@app.command()
def schedule() -> None:
    """Start the scheduler daemon (9 AM + 4 PM IST by default)."""
    _configure_logging()
    from scheduler.runner import start_scheduler

    typer.echo("Starting scheduler daemon...")
    start_scheduler(settings)


@app.command()
def login(
    platform: str = typer.Argument(help="Platform to login to (e.g. instahyre, linkedin)"),
) -> None:
    """Open a headed browser for manual login and save cookies."""
    _configure_logging()
    from services.cookie_manager import interactive_login

    asyncio.run(interactive_login(platform, settings.COOKIES_DIR))


@app.command()
def export() -> None:
    """Re-export all jobs from DB to CSV and Excel."""
    _configure_logging()
    from storage.db import JobDB
    from services.exporter import export_csv, export_excel

    db = JobDB()
    all_jobs = db.get_all_jobs()
    db.close()

    if not all_jobs:
        typer.echo("No jobs in database.")
        return

    export_csv(all_jobs, settings.OUTPUT_DIR)
    export_excel(all_jobs, [], settings.OUTPUT_DIR)
    typer.echo(f"Exported {len(all_jobs)} jobs to {settings.OUTPUT_DIR}")


@app.command()
def status() -> None:
    """Show last run summary and cookie health."""
    _configure_logging()
    from storage.db import JobDB
    from services.cookie_manager import has_cookies, LOGIN_URLS

    db = JobDB()
    last_run = db.get_last_run()
    db.close()

    if last_run:
        typer.echo(f"Last run: {last_run['timestamp']}")
        typer.echo(f"  New: {last_run['new_count']}, Duplicates: {last_run['duplicate_count']}")
        typer.echo(f"  Platforms: {', '.join(last_run['platforms_scraped'])}")
        if last_run["errors"]:
            typer.echo(f"  Errors: {last_run['errors']}")
    else:
        typer.echo("No runs recorded yet.")

    typer.echo("\nCookie status:")
    for p in LOGIN_URLS:
        status = "OK" if has_cookies(p, settings.COOKIES_DIR) else "MISSING"
        typer.echo(f"  {p}: {status}")


@app.command()
def funding() -> None:
    """Scan funding news (Inc42, YourStory, Entrackr, VCCircle) and check LinkedIn for PM roles."""
    _configure_logging()
    asyncio.run(_run_funding())


async def _run_funding() -> None:
    from browser.context import BrowserManager
    from funding.scanner import FundingScanner
    from funding.exporter import export_funding_csv, export_funding_excel

    typer.echo("Scanning funding news sources...\n")

    async with BrowserManager() as bm:
        scanner = FundingScanner(bm)
        companies = await scanner.scan_all()
        typer.echo(f"Found {len(companies)} recently funded companies.\n")

        if companies:
            typer.echo("Cross-referencing with LinkedIn for PM roles...")
            await scanner.check_linkedin_pm_roles(companies)

    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_funding_csv(companies, settings.OUTPUT_DIR)
    export_funding_excel(companies, settings.OUTPUT_DIR)

    # Summary
    with_roles = sum(1 for c in companies if c.linkedin_pm_roles > 0)
    typer.echo(f"\nDone: {len(companies)} funded companies, {with_roles} with open PM roles on LinkedIn.")
    typer.echo(f"Output: {settings.OUTPUT_DIR}")


@app.command()
def vc_jobs() -> None:
    """Scrape VC portfolio job portals for PM roles."""
    _configure_logging()
    asyncio.run(_run_vc_jobs())


async def _run_vc_jobs() -> None:
    from browser.context import BrowserManager
    from storage.db import JobDB
    from vc_portals.scraper import VCPortalScraper
    from services.exporter import export_csv
    from services.location_filter import is_acceptable_location, explain as explain_location

    typer.echo("Scanning VC portfolio job portals...\n")

    async with BrowserManager() as bm:
        scraper = VCPortalScraper(bm)
        jobs = await scraper.scrape_all()

    accepted = [j for j in jobs if is_acceptable_location(j.location)]
    rejected = len(jobs) - len(accepted)
    if rejected:
        typer.echo(f"  Location filter: rejected {rejected} out-of-scope jobs.")

    if accepted:
        db = JobDB()
        try:
            inserted, skipped = db.insert_jobs(accepted)
            typer.echo(f"\nVC portals: {inserted} new, {skipped} existing")
            settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            export_csv([j.model_dump() for j in accepted], settings.OUTPUT_DIR)
        finally:
            db.close()
    else:
        typer.echo("No PM roles found on VC portals.")


@app.command()
def mnc_jobs() -> None:
    """Scrape US MNC career pages for PM roles in Delhi NCR."""
    _configure_logging()
    asyncio.run(_run_mnc_jobs())


async def _run_mnc_jobs() -> None:
    from browser.context import BrowserManager
    from storage.db import JobDB
    from mnc_careers.scraper import MNCCareerScraper
    from services.location_filter import is_acceptable_location

    typer.echo("Scanning US MNC career pages...\n")

    async with BrowserManager() as bm:
        scraper = MNCCareerScraper(bm)
        jobs = await scraper.scrape_all()

    accepted = [j for j in jobs if is_acceptable_location(j.location)]
    rejected = len(jobs) - len(accepted)
    if rejected:
        typer.echo(f"  Location filter: rejected {rejected} out-of-scope jobs.")

    if accepted:
        db = JobDB()
        try:
            inserted, skipped = db.insert_jobs(accepted)
            typer.echo(f"\nMNC careers: {inserted} new, {skipped} existing")
        finally:
            db.close()
    else:
        typer.echo("No PM roles found on MNC career pages.")


@app.command(name="run-all")
def run_all_sources() -> None:
    """Run everything: job platforms + VC portals + MNC careers + funding scan."""
    _configure_logging()
    asyncio.run(_run_everything())


async def _run_everything() -> None:
    typer.echo("=" * 60)
    typer.echo("FULL SCAN: Job Platforms + VC Portals + MNC Careers + Funding")
    typer.echo("=" * 60)

    typer.echo("\n[1/4] Job Platforms")
    await _run_all()

    typer.echo("\n[2/4] VC Portfolio Job Portals")
    await _run_vc_jobs()

    typer.echo("\n[3/4] US MNC Career Pages")
    await _run_mnc_jobs()

    typer.echo("\n[4/4] Funding Scanner")
    await _run_funding()

    typer.echo("\n" + "=" * 60)
    typer.echo("FULL SCAN COMPLETE")
    typer.echo("=" * 60)


# ------------------------------------------------------------------
# Outreach commands
# ------------------------------------------------------------------

@app.command(name="outreach-enrich")
def outreach_enrich() -> None:
    """Find contacts at target companies (Apollo) and generate email drafts."""
    _configure_logging()
    from outreach.pipeline import run_enrich

    typer.echo("Starting outreach enrichment...\n")
    asyncio.run(run_enrich(settings))


@app.command(name="outreach-review")
def outreach_review() -> None:
    """Open browser-based review page for draft outreach emails."""
    _configure_logging()
    from outreach.db import OutreachDB
    from outreach.reviewer import start_review_server

    db = OutreachDB()
    start_review_server(db)
    db.close()


@app.command(name="outreach-send")
def outreach_send() -> None:
    """Send approved outreach emails via Gmail API."""
    _configure_logging()
    from outreach.pipeline import run_send

    typer.echo("Sending approved outreach emails...\n")
    run_send(settings)


@app.command(name="outreach-status")
def outreach_status() -> None:
    """Show outreach pipeline status and credit usage."""
    _configure_logging()
    from outreach.pipeline import show_status

    show_status(settings)


@app.command(name="outreach-reply")
def outreach_reply(
    contact_id: str = typer.Argument(help="Contact ID to mark as replied"),
) -> None:
    """Mark a contact as replied and cancel pending follow-ups."""
    _configure_logging()
    from outreach.pipeline import mark_replied

    mark_replied(contact_id)



# ------------------------------------------------------------------
# P0: Scoring + Recommend
# ------------------------------------------------------------------

@app.command()
def recommend(
    top: int = typer.Option(25, "--top", "-n", help="Number of jobs to show"),
    min_score: int = typer.Option(0, "--min-score", help="Minimum priority score"),
    bucket: Optional[str] = typer.Option(None, "--bucket", "-b", help="Filter by bucket: must_apply|high|medium|low"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filter by platform"),
    remote_only: bool = typer.Option(False, "--remote-only", help="Only remote roles"),
    include_low: bool = typer.Option(False, "--include-low", help="Include low-priority jobs"),
    rescore: bool = typer.Option(False, "--rescore", help="Force rescore all jobs"),
) -> None:
    """Score and rank jobs, then print the top shortlist."""
    _configure_logging()
    from storage.db import JobDB
    from services.scoring import score_job, _company_slug
    from services.company_intel import build_company_profiles, enrich_from_funding_data
    import json

    db = JobDB()
    try:
        # Refresh company intel first
        typer.echo("Refreshing company intelligence cache...")
        n_profiles = build_company_profiles(db)
        n_funded = enrich_from_funding_data(db)
        typer.echo(f"  {n_profiles} company profiles indexed.")
        typer.echo(f"  {n_funded} funded companies refreshed.\n")

        company_profiles = db.get_all_company_profiles()

        # Score unscored (or all if --rescore)
        to_score = db.get_jobs_for_scoring(rescore_all=rescore)
        if to_score:
            typer.echo(f"Scoring {len(to_score)} job(s)...")
            for job in to_score:
                profile = company_profiles.get(_company_slug(job.get("company", "")))
                scores = score_job(job, profile)
                db.update_job_scores(job["id"], scores)
            typer.echo(f"  Done.\n")

        # Fetch ranked list
        jobs = db.get_top_recommended_jobs(
            top_n=top,
            min_score=min_score,
            bucket=bucket,
            platform=platform,
            remote_only=remote_only,
            include_low=include_low,
        )

        if not jobs:
            typer.echo("No jobs match the criteria. Try --include-low or lower --min-score.")
            return

        typer.echo(f"{'#':<3} {'Score':<6} {'Bucket':<12} {'Title':<38} {'Company':<28} {'Platform':<14} Reasons")
        typer.echo("-" * 130)
        for i, job in enumerate(jobs, 1):
            reasons_raw = job.get("score_reasons") or "[]"
            try:
                reasons = json.loads(reasons_raw)
            except Exception:
                reasons = []
            flags_raw = job.get("priority_flags") or "[]"
            try:
                flags = json.loads(flags_raw)
            except Exception:
                flags = []
            reasons_str = ", ".join(reasons[:4])
            flag_str = f"  ⚑ {', '.join(flags[:2])}" if flags else ""
            typer.echo(
                f"{i:<3} {job.get('priority_score', 0):<6} {job.get('priority_bucket', ''):<12} "
                f"{job.get('title', '')[:37]:<38} {job.get('company', '')[:27]:<28} "
                f"{job.get('platform', ''):<14} {reasons_str}{flag_str}"
            )
            typer.echo(f"    {job.get('apply_link', '')[:110]}")

        # Export to CSV
        import csv
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = settings.OUTPUT_DIR / f"recommended_jobs_{ts}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "priority_score", "priority_bucket", "title", "company",
                "location", "platform", "score_reasons", "priority_flags",
                "apply_link", "posted_date", "scraped_at",
            ])
            writer.writeheader()
            for job in jobs:
                writer.writerow({k: job.get(k, "") for k in writer.fieldnames})
        typer.echo(f"\nExported {len(jobs)} jobs → {csv_path}")
    finally:
        db.close()


@app.command(name="company-intel-refresh")
def company_intel_refresh() -> None:
    """Build/refresh company intelligence cache from local data."""
    _configure_logging()
    from storage.db import JobDB
    from services.company_intel import build_company_profiles, enrich_from_funding_data

    db = JobDB()
    try:
        typer.echo("Building company profiles from MNC registry, VC registry, and scraped jobs...")
        n = build_company_profiles(db)
        typer.echo(f"  {n} company profiles upserted.")

        typer.echo("Enriching from funding scan data...")
        n_funded = enrich_from_funding_data(db)
        typer.echo(f"  {n_funded} companies marked as funded.")
    finally:
        db.close()


# ------------------------------------------------------------------
# P0: Connections import
# ------------------------------------------------------------------

@app.command(name="connections-import")
def connections_import(
    csv_path: str = typer.Argument(help="Path to LinkedIn connections export CSV"),
    alumni_colleges: Optional[list[str]] = typer.Option(
        None, "--alumni", "-a", help="College name(s) to mark contacts as alumni"
    ),
) -> None:
    """Import LinkedIn connections CSV and match against scraped jobs."""
    _configure_logging()
    from pathlib import Path as _Path
    from storage.db import JobDB
    from services.connection_matcher import import_connections_csv, match_connections_to_jobs

    csv_file = _Path(csv_path)
    if not csv_file.exists():
        typer.echo(f"File not found: {csv_path}", err=True)
        raise typer.Exit(1)

    db = JobDB()
    try:
        typer.echo(f"Importing contacts from {csv_path}...")
        n_imported = import_connections_csv(csv_file, db, alumni_colleges or [])
        typer.echo(f"  {n_imported} contacts imported/updated.")

        typer.echo("Matching contacts to scraped jobs...")
        n_matched = match_connections_to_jobs(db)
        typer.echo(f"  {n_matched} jobs have warm connection(s).")
        typer.echo("\nRun 'recommend' to see updated warmth scores.")
    finally:
        db.close()


# ------------------------------------------------------------------
# P1: Application tracker
# ------------------------------------------------------------------

@app.command(name="shortlist")
def shortlist(
    job_id: str = typer.Option(..., "--job-id", "-j", help="Job ID to shortlist"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n"),
) -> None:
    """Mark a job as shortlisted for application."""
    _configure_logging()
    from datetime import datetime as _dt
    from storage.db import JobDB, application_id_for

    db = JobDB()
    try:
        job = db.get_job_by_id(job_id)
        if not job:
            typer.echo(f"Job {job_id!r} not found.", err=True)
            raise typer.Exit(1)

        app_id = application_id_for(job_id)
        now = _dt.now().isoformat()
        db.upsert_application({
            "id": app_id,
            "job_id": job_id,
            "company": job.get("company"),
            "title": job.get("title"),
            "status": "shortlisted",
            "last_action_at": now,
            "notes": notes,
        })
        typer.echo(f"Shortlisted: {job.get('title')} @ {job.get('company')}")
    finally:
        db.close()


@app.command(name="apply-status")
def apply_status_cmd(
    job_id: str = typer.Option(..., "--job-id", "-j", help="Job ID"),
    status: str = typer.Option(..., "--status", "-s",
        help="Status: to_review|shortlisted|reached_out|applied|screening|interview|offer|rejected|parked|skipped"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n"),
) -> None:
    """Update the application status for a job."""
    _configure_logging()
    from storage.db import JobDB, APPLICATION_STATUSES

    if status not in APPLICATION_STATUSES:
        typer.echo(
            f"Invalid status '{status}'. Choose from: {', '.join(sorted(APPLICATION_STATUSES))}",
            err=True,
        )
        raise typer.Exit(1)

    db = JobDB()
    try:
        updated = db.update_application_status(job_id, status, notes)
        if updated:
            typer.echo(f"Updated job {job_id} → {status}")
        else:
            typer.echo(f"No application found for job {job_id}. Use 'shortlist' first.", err=True)
    finally:
        db.close()


@app.command(name="pipeline-status")
def pipeline_status() -> None:
    """Show application pipeline summary."""
    _configure_logging()
    from storage.db import JobDB

    db = JobDB()
    try:
        stats = db.get_pipeline_stats()
        typer.echo("\n=== Job Search Pipeline ===")
        typer.echo(f"  Total jobs (non-duplicate): {stats['total_jobs']}")
        typer.echo(f"  Scored jobs:                {stats['scored_jobs']}")
        typer.echo(f"\n  By bucket:")
        for b in ("must_apply", "high", "medium", "low"):
            typer.echo(f"    {b:<14} {stats.get(f'bucket_{b}', 0)}")
        typer.echo(f"\n  Applications: {stats['total_applications']}")
        for s, n in (stats.get("applications_by_status") or {}).items():
            typer.echo(f"    {s:<16} {n}")
        typer.echo(f"\n  Network contacts: {stats['network_contacts']}")
        typer.echo(f"  Company profiles: {stats['company_profiles']}")
    finally:
        db.close()


# ------------------------------------------------------------------
# P1: Daily action queue
# ------------------------------------------------------------------

@app.command()
def today() -> None:
    """Print today's action queue: what to apply to, reach out to, follow up on."""
    _configure_logging()
    from storage.db import JobDB, STATUSES_COUNTING_AS_APPLIED
    from services.scoring import score_job, _company_slug
    from services.company_intel import build_company_profiles, enrich_from_funding_data
    import json
    from datetime import datetime as _dt, timedelta

    db = JobDB()
    try:
        # Ensure scoring is up to date
        build_company_profiles(db)
        enrich_from_funding_data(db)
        to_score = db.get_jobs_for_scoring(rescore_all=False)
        if to_score:
            company_profiles = db.get_all_company_profiles()
            for job in to_score:
                profile = company_profiles.get(_company_slug(job.get("company", "")))
                scores = score_job(job, profile)
                db.update_job_scores(job["id"], scores)

        typer.echo("\n" + "=" * 60)
        typer.echo("TODAY'S JOB SEARCH ACTION QUEUE")
        typer.echo("=" * 60)

        # 1. Top jobs to apply now
        typer.echo("\n[ TOP 5 TO APPLY NOW ]")
        top_jobs = db.get_top_recommended_jobs(top_n=5, bucket=None, include_low=False)
        must_high = [j for j in top_jobs if j.get("priority_bucket") in ("must_apply", "high")]
        if must_high:
            for j in must_high[:5]:
                typer.echo(f"  [{j.get('priority_score',0):>3}] {j.get('title','')[:40]:40} @ {j.get('company','')[:25]:25} ({j.get('platform','')})")
                typer.echo(f"       {j.get('apply_link','')[:90]}")
        else:
            typer.echo("  None scored as must_apply/high yet. Run 'recommend' first.")

        # 2. Warm leads
        typer.echo("\n[ TOP 3 WARM LEADS ]")
        all_jobs = db.get_all_jobs()
        warm_jobs = sorted(
            [j for j in all_jobs if (j.get("warmth_score") or 0) > 0 and not j.get("is_duplicate")],
            key=lambda j: j.get("warmth_score", 0),
            reverse=True,
        )[:3]
        if warm_jobs:
            for j in warm_jobs:
                matches = db.get_connection_matches_for_job(j["id"])
                contact_names = ", ".join(m.get("contact_name", "") for m in matches[:2])
                typer.echo(f"  [warmth={j.get('warmth_score',0)}] {j.get('title','')[:38]:38} @ {j.get('company','')}")
                typer.echo(f"    Connections: {contact_names or '(unknown)'}")
        else:
            typer.echo("  No warm connections matched yet. Run 'connections-import'.")

        # 3. Follow-ups due
        typer.echo("\n[ FOLLOW-UPS DUE ]")
        apps = db.get_applications()
        cutoff = (_dt.now() - timedelta(days=3)).isoformat()
        due = [
            a for a in apps
            if a.get("status") in STATUSES_COUNTING_AS_APPLIED
            and (a.get("last_action_at") or "") < cutoff
        ]
        if due:
            for a in due[:3]:
                typer.echo(f"  {a.get('status',''):<14} {a.get('title','')[:38]:38} @ {a.get('company','')}")
                typer.echo(f"    Last action: {a.get('last_action_at','')[:10]}")
        else:
            typer.echo("  No follow-ups overdue.")

        # 4. Stale applications to review
        typer.echo("\n[ SHORTLISTED BUT NOT APPLIED ]")
        shortlisted = [a for a in apps if a.get("status") == "shortlisted"]
        if shortlisted:
            for a in shortlisted[:3]:
                typer.echo(f"  {a.get('title','')[:45]:45} @ {a.get('company','')}")
        else:
            typer.echo("  None.")

        typer.echo("\n" + "=" * 60)
        typer.echo("Run 'recommend' for full ranked list | 'pipeline-status' for stats")
        typer.echo("=" * 60 + "\n")
    finally:
        db.close()


# ------------------------------------------------------------------
# P1: Draft message
# ------------------------------------------------------------------

@app.command(name="draft-message")
def draft_message_cmd(
    job_id: str = typer.Option(..., "--job-id", "-j", help="Job ID to draft message for"),
    msg_type: str = typer.Option("recruiter", "--type", "-t",
        help="Message type: recruiter|hiring-manager|funded-startup|warm-intro"),
    contact_name: str = typer.Option("", "--contact", "-c", help="Recipient name"),
    mutual_name: str = typer.Option("", "--mutual", help="Mutual connection name (warm-intro)"),
    funding_context: str = typer.Option("", "--funding", help="Funding context, e.g. 'Series B'"),
    save: bool = typer.Option(False, "--save", help="Save draft to output/drafts/"),
) -> None:
    """Generate a tailored recruiter/hiring-manager outreach message for a job."""
    _configure_logging()
    from storage.db import JobDB
    from services.outreach_writer import draft_message
    from datetime import datetime as _dt

    db = JobDB()
    try:
        job = db.get_job_by_id(job_id)
        if not job:
            typer.echo(f"Job {job_id!r} not found.", err=True)
            raise typer.Exit(1)

        typer.echo(f"\nDrafting '{msg_type}' message for: {job.get('title')} @ {job.get('company')}\n")
        typer.echo("-" * 60)

        message = draft_message(
            job=job,
            message_type=msg_type,
            contact_name=contact_name,
            mutual_name=mutual_name,
            funding_context=funding_context,
        )
        typer.echo(message)
        typer.echo("-" * 60)

        if save:
            drafts_dir = settings.OUTPUT_DIR / "drafts"
            drafts_dir.mkdir(parents=True, exist_ok=True)
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            safe_co = re.sub(r"[^a-z0-9]", "_", job.get("company", "company").lower())
            draft_path = drafts_dir / f"{ts}_{msg_type}_{safe_co}.txt"
            draft_path.write_text(message, encoding="utf-8")
            typer.echo(f"\nSaved to {draft_path}")
    finally:
        db.close()


# ------------------------------------------------------------------
# P2: Analytics
# ------------------------------------------------------------------

@app.command()
def analytics() -> None:
    """Show source quality stats and conversion analytics."""
    _configure_logging()
    from storage.db import JobDB

    db = JobDB()
    try:
        typer.echo("\n=== Source Quality ===")
        source_stats = db.get_source_quality_stats()
        typer.echo(f"{'Platform':<18} {'Total':<8} {'Avg Score':<12} {'High Quality'}")
        typer.echo("-" * 55)
        for row in source_stats:
            typer.echo(
                f"{row['platform']:<18} {row['total']:<8} "
                f"{row['avg_score'] or 0:>6.1f}      {row['high_quality']}"
            )

        typer.echo("\n=== Pipeline Stats ===")
        stats = db.get_pipeline_stats()
        typer.echo(f"  Total jobs:   {stats['total_jobs']}")
        typer.echo(f"  Scored:       {stats['scored_jobs']}")
        for b in ("must_apply", "high", "medium", "low"):
            typer.echo(f"  {b:<14} {stats.get(f'bucket_{b}', 0)}")

        typer.echo("\n=== Applications ===")
        apps_by_status = stats.get("applications_by_status") or {}
        if apps_by_status:
            for s, n in apps_by_status.items():
                typer.echo(f"  {s:<16} {n}")
        else:
            typer.echo("  No applications tracked yet.")
    finally:
        db.close()


# ------------------------------------------------------------------
# Full end-to-end run
# ------------------------------------------------------------------

@app.command(name="full-run")
def full_run(
    skip_vc: bool = typer.Option(False, "--skip-vc", help="Skip VC portal scraping"),
    skip_mnc: bool = typer.Option(False, "--skip-mnc", help="Skip MNC career page scraping"),
    skip_funding: bool = typer.Option(False, "--skip-funding", help="Skip funding news scan"),
    top: int = typer.Option(25, "--top", "-n", help="Number of jobs to show in recommend output"),
) -> None:
    """
    Full end-to-end pipeline:
      1. Scrape all 14 job platforms
      2. VC portfolio job portals        (--skip-vc to skip)
      3. US MNC career pages             (--skip-mnc to skip)
      4. Funding news scan               (--skip-funding to skip)
      5. Score & rank all jobs
      6. Today's action queue
      7. Export to CSV + Excel
      8. Analytics summary
    """
    _configure_logging()
    asyncio.run(_full_run_async(skip_vc=skip_vc, skip_mnc=skip_mnc, skip_funding=skip_funding, top=top))


async def _full_run_async(
    skip_vc: bool = False,
    skip_mnc: bool = False,
    skip_funding: bool = False,
    top: int = 25,
) -> None:
    import time
    import json
    from datetime import datetime as _dt, timedelta
    from storage.db import JobDB, STATUSES_COUNTING_AS_APPLIED
    from services.scoring import score_job, _company_slug
    from services.company_intel import build_company_profiles, enrich_from_funding_data
    from services.exporter import export_csv, export_excel

    overall_start = time.time()

    def _banner(step: str, title: str) -> None:
        typer.echo(f"\n{'─' * 60}")
        typer.echo(f"  {step}  {title}")
        typer.echo(f"{'─' * 60}")

    def _elapsed(since: float) -> str:
        s = int(time.time() - since)
        return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"

    # ── STEP 1: Job platforms ──────────────────────────────────────
    _banner("[1/8]", "Scraping 14 job platforms")
    t = time.time()
    await _run_all()
    typer.echo(f"  ✓ Platforms done  ({_elapsed(t)})")

    # ── STEP 2: VC portals ─────────────────────────────────────────
    if not skip_vc:
        _banner("[2/8]", "VC portfolio job portals")
        t = time.time()
        await _run_vc_jobs()
        typer.echo(f"  ✓ VC portals done  ({_elapsed(t)})")
    else:
        typer.echo("\n[2/8] VC portals — SKIPPED (--skip-vc)")

    # ── STEP 3: MNC careers ────────────────────────────────────────
    if not skip_mnc:
        _banner("[3/8]", "US MNC career pages")
        t = time.time()
        await _run_mnc_jobs()
        typer.echo(f"  ✓ MNC careers done  ({_elapsed(t)})")
    else:
        typer.echo("\n[3/8] MNC careers — SKIPPED (--skip-mnc)")

    # ── STEP 4: Funding scan ───────────────────────────────────────
    if not skip_funding:
        _banner("[4/8]", "Funding news scan (Inc42, YourStory, Entrackr, VCCircle)")
        t = time.time()
        await _run_funding()
        typer.echo(f"  ✓ Funding scan done  ({_elapsed(t)})")
    else:
        typer.echo("\n[4/8] Funding scan — SKIPPED (--skip-funding)")

    # ── STEP 5: Score & rank ───────────────────────────────────────
    _banner("[5/8]", "Scoring & ranking all jobs")
    t = time.time()
    db = JobDB()
    try:
        n_profiles = build_company_profiles(db)
        n_funded = enrich_from_funding_data(db)
        typer.echo(f"  Company profiles: {n_profiles}  |  Funded companies: {n_funded}")

        company_profiles = db.get_all_company_profiles()
        to_score = db.get_jobs_for_scoring(rescore_all=False)
        if to_score:
            typer.echo(f"  Scoring {len(to_score)} unscored job(s)...")
            for job in to_score:
                profile = company_profiles.get(_company_slug(job.get("company", "")))
                scores = score_job(job, profile)
                db.update_job_scores(job["id"], scores)
            typer.echo(f"  ✓ Scoring done  ({_elapsed(t)})")
        else:
            typer.echo("  All jobs already scored.")

        # ── STEP 6: Today's action queue ──────────────────────────
        _banner("[6/8]", "Today's action queue")
        top_jobs = db.get_top_recommended_jobs(top_n=top, bucket=None, include_low=False)
        must_high = [j for j in top_jobs if j.get("priority_bucket") in ("must_apply", "high")]

        typer.echo(f"\n  TOP PICKS TO APPLY NOW  (must_apply / high bucket, top {top})")
        typer.echo(f"  {'Score':<6} {'Bucket':<13} {'Title':<38} {'Company':<28} {'Platform'}")
        typer.echo("  " + "─" * 100)
        if must_high:
            for j in must_high[:top]:
                typer.echo(
                    f"  {j.get('priority_score', 0):<6} {j.get('priority_bucket', ''):<13} "
                    f"{j.get('title', '')[:37]:<38} {j.get('company', '')[:27]:<28} "
                    f"{j.get('platform', '')}"
                )
                typer.echo(f"    → {j.get('apply_link', '')[:100]}")
        else:
            typer.echo("  No must_apply/high jobs yet.")

        # Warm leads
        all_jobs = db.get_all_jobs()
        warm_jobs = sorted(
            [j for j in all_jobs if (j.get("warmth_score") or 0) > 0 and not j.get("is_duplicate")],
            key=lambda j: j.get("warmth_score", 0),
            reverse=True,
        )[:3]
        typer.echo(f"\n  WARM LEADS")
        if warm_jobs:
            for j in warm_jobs:
                matches = db.get_connection_matches_for_job(j["id"])
                names = ", ".join(m.get("contact_name", "") for m in matches[:2])
                typer.echo(f"  [warmth={j.get('warmth_score',0)}] {j.get('title','')[:38]:38} @ {j.get('company','')}")
                typer.echo(f"    Connections: {names or '(unknown)'}")
        else:
            typer.echo("  None — run 'connections-import' to match LinkedIn contacts.")

        # Follow-ups
        apps = db.get_applications()
        cutoff = (_dt.now() - timedelta(days=3)).isoformat()
        due = [a for a in apps if a.get("status") in STATUSES_COUNTING_AS_APPLIED and (a.get("last_action_at") or "") < cutoff]
        typer.echo(f"\n  FOLLOW-UPS OVERDUE")
        if due:
            for a in due[:3]:
                typer.echo(f"  {a.get('status',''):<14} {a.get('title','')[:38]:38} @ {a.get('company','')}  (last: {(a.get('last_action_at',''))[:10]})")
        else:
            typer.echo("  None overdue.")

        # ── STEP 7: Export ─────────────────────────────────────────
        _banner("[7/8]", "Exporting CSV + Excel")
        t = time.time()
        settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        all_jobs_export = db.get_all_jobs()
        csv_path = export_csv(all_jobs_export, settings.OUTPUT_DIR)
        export_excel(all_jobs_export, [], settings.OUTPUT_DIR)
        typer.echo(f"  ✓ Exported {len(all_jobs_export)} jobs → {settings.OUTPUT_DIR}  ({_elapsed(t)})")

        # ── STEP 8: Analytics summary ──────────────────────────────
        _banner("[8/8]", "Analytics summary")
        source_stats = db.get_source_quality_stats()
        typer.echo(f"  {'Platform':<18} {'Total':<8} {'Avg Score':<12} High Quality")
        typer.echo("  " + "─" * 55)
        for row in source_stats:
            typer.echo(
                f"  {row['platform']:<18} {row['total']:<8} "
                f"{row['avg_score'] or 0:>6.1f}      {row['high_quality']}"
            )

        stats = db.get_pipeline_stats()
        typer.echo(f"\n  Total jobs (non-duplicate): {stats['total_jobs']}")
        typer.echo(f"  Scored:                     {stats['scored_jobs']}")
        for b in ("must_apply", "high", "medium", "low"):
            typer.echo(f"    {b:<14} {stats.get(f'bucket_{b}', 0)}")

    finally:
        db.close()

    # ── Done ───────────────────────────────────────────────────────
    typer.echo(f"\n{'═' * 60}")
    typer.echo(f"  FULL RUN COMPLETE  —  total time: {_elapsed(overall_start)}")
    typer.echo(f"  Output: {settings.OUTPUT_DIR}")
    typer.echo(f"{'═' * 60}\n")


@app.command(name="purge-jobs")
def purge_jobs(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    keep_applications: bool = typer.Option(
        True, "--keep-applications/--drop-applications",
        help="Preserve the applications tracker (default: keep)",
    ),
) -> None:
    """
    Wipe scraped jobs from the DB so you can re-scrape cleanly.

    By default this keeps your application tracker intact — only the scraped
    jobs, runs, company profiles, and connection matches are cleared.
    Pass --drop-applications to also wipe the tracker.
    """
    from storage.db import JobDB
    _configure_logging()

    db = JobDB()
    try:
        job_count = db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        run_count = db.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        app_count = db.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

        typer.echo("\n  About to PURGE the following tables:")
        typer.echo(f"    jobs:              {job_count:>6} rows")
        typer.echo(f"    runs:              {run_count:>6} rows")
        typer.echo(f"    company_profiles:  (all)")
        typer.echo(f"    job_connection_matches: (all)")
        if keep_applications:
            typer.echo(f"    applications:      {app_count:>6} rows  [PRESERVED]")
        else:
            typer.echo(f"    applications:      {app_count:>6} rows  [WILL BE DROPPED]")
        typer.echo()

        if not yes:
            confirm = typer.confirm("  Are you sure? This cannot be undone")
            if not confirm:
                typer.echo("  Aborted.")
                return

        db.conn.execute("DELETE FROM jobs")
        db.conn.execute("DELETE FROM runs")
        db.conn.execute("DELETE FROM company_profiles")
        db.conn.execute("DELETE FROM job_connection_matches")
        if not keep_applications:
            db.conn.execute("DELETE FROM applications")
        db.conn.commit()
        db.conn.execute("VACUUM")

        typer.echo("\n  ✓ Purge complete. Run `python main.py run` to repopulate.\n")
    finally:
        db.close()


# ─── YC Startups ─────────────────────────────────────────────────────────────


@app.command(name="purge-titles")
def purge_titles(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """
    Remove jobs whose title does not contain both 'product' and 'manager'.

    Jobs with existing application tracker rows are always preserved.
    Run this once after deploying the title filter to clean up historical data.
    """
    from storage.db import JobDB
    _configure_logging()

    db = JobDB()
    try:
        to_delete = db.conn.execute(
            """SELECT COUNT(*) FROM jobs
               WHERE (LOWER(title) NOT LIKE '%product%' OR LOWER(title) NOT LIKE '%manager%')
               AND id NOT IN (SELECT job_id FROM applications WHERE job_id IS NOT NULL)"""
        ).fetchone()[0]

        if to_delete == 0:
            typer.echo("  No irrelevant titles found — DB is already clean.")
            return

        typer.echo(f"\n  Found {to_delete} jobs with titles that don't match 'product' + 'manager'.")
        typer.echo("  Jobs with application tracker rows will be preserved.\n")

        if not yes:
            confirm = typer.confirm("  Delete them?")
            if not confirm:
                typer.echo("  Aborted.")
                return

        deleted = db.purge_irrelevant_titles()
        typer.echo(f"\n  ✓ Deleted {deleted} jobs. Run `python main.py recommend --rescore` to refresh scores.\n")
    finally:
        db.close()


@app.command(name="yc-sync")
def yc_sync(
    batch: Optional[str] = typer.Option(None, "--batch", "-b", help="Filter by YC batch (e.g. S24, W24)"),
    limit: int = typer.Option(0, "--limit", help="Max companies to fetch (0 = all)"),
    check_signals: bool = typer.Option(True, "--signals/--no-signals", help="Check hiring signals after sync"),
) -> None:
    """Sync Y Combinator company directory and optionally check hiring signals."""
    _configure_logging()
    asyncio.run(_run_yc_sync(batch, limit, check_signals))


async def _run_yc_sync(batch: Optional[str], limit: int, check_signals: bool) -> None:
    from storage.db import JobDB
    from yc_startups.scraper import sync_yc_directory
    from yc_startups.signals import check_hiring_signals

    batch_filter = [b.strip() for b in batch.split(",")] if batch else None

    typer.echo("Syncing YC company directory...\n")
    companies = await sync_yc_directory(batch_filter=batch_filter, limit=limit)
    typer.echo(f"  Fetched {len(companies)} YC companies")

    if not companies:
        typer.echo("No companies found. Check network connectivity.", err=True)
        return

    db = JobDB()
    try:
        # Convert to dicts and upsert
        company_dicts = []
        for c in companies:
            company_dicts.append({
                "id": c.id,
                "company_slug": c.slug,
                "company_name": c.name,
                "description": c.description,
                "long_description": c.long_description,
                "batch": c.batch,
                "website": c.website,
                "hq_location": c.hq_location,
                "team_size": c.team_size,
                "industry": c.industry,
                "subindustry": c.subindustry,
                "status": c.status,
                "logo_url": c.logo_url,
                "founders": c.founders,
                "is_hiring": int(c.is_hiring),
                "is_hiring_pm": int(c.is_hiring_pm),
                "last_refreshed_at": c.last_refreshed_at,
            })

        count = db.upsert_yc_companies(company_dicts)
        typer.echo(f"  Upserted {count} companies into DB")

        # Batch summary
        batches: dict[str, int] = {}
        for c in companies:
            batches[c.batch] = batches.get(c.batch, 0) + 1
        hiring_count = sum(1 for c in companies if c.is_hiring)
        typer.echo(f"  Hiring (self-reported): {hiring_count}")
        typer.echo(f"  Batches: {len(batches)} ({', '.join(list(batches.keys())[:5])}...)")

        if check_signals:
            typer.echo("\nChecking hiring signals...")
            signals = await check_hiring_signals(company_dicts, db)
            for s in signals:
                sig_dict = {
                    "id": s.id,
                    "company_id": s.company_id,
                    "signal_type": s.signal_type,
                    "signal_source": s.signal_source,
                    "signal_date": s.signal_date,
                    "signal_detail": s.signal_detail,
                    "checked_at": s.checked_at,
                }
                db.upsert_yc_hiring_signal(sig_dict)
            db.conn.commit()
            typer.echo(f"  Found {len(signals)} hiring signals")

            # Mark companies with PM hiring signals
            pm_company_ids = set()
            for s in signals:
                if "PM" in s.signal_detail or s.signal_type == "scraped_job":
                    pm_company_ids.add(s.company_id)
            for cid in pm_company_ids:
                db.update_yc_hiring_status(cid, is_hiring_pm=True)
            db.conn.commit()
            if pm_company_ids:
                typer.echo(f"  PM hiring detected: {len(pm_company_ids)} companies")

        stats = db.get_yc_stats()
        typer.echo(f"\nYC Database: {stats['total_companies']} companies, "
                    f"{stats['hiring_companies']} hiring, {stats['hiring_pm']} hiring PM, "
                    f"{stats['total_founders']} founders, {stats['verified_emails']} verified emails")
    finally:
        db.close()


@app.command(name="yc-hiring-check")
def yc_hiring_check(
    batch: Optional[str] = typer.Option(None, "--batch", "-b", help="Filter by batch"),
    force: bool = typer.Option(False, "--force", help="Rescan all companies"),
) -> None:
    """Check which YC companies are actively hiring for PM roles."""
    _configure_logging()
    asyncio.run(_run_yc_hiring_check(batch, force))


async def _run_yc_hiring_check(batch: Optional[str], force: bool) -> None:
    from storage.db import JobDB
    from yc_startups.signals import check_hiring_signals

    db = JobDB()
    try:
        companies = db.get_yc_companies(batch=batch or "", hiring_only=not force)
        if not companies:
            companies = db.get_yc_companies(batch=batch or "")
        typer.echo(f"Checking hiring signals for {len(companies)} companies...\n")

        signals = await check_hiring_signals(companies, db)
        for s in signals:
            sig_dict = {
                "id": s.id,
                "company_id": s.company_id,
                "signal_type": s.signal_type,
                "signal_source": s.signal_source,
                "signal_date": s.signal_date,
                "signal_detail": s.signal_detail,
                "checked_at": s.checked_at,
            }
            db.upsert_yc_hiring_signal(sig_dict)

        # Update PM hiring flags
        pm_company_ids = set()
        for s in signals:
            if "PM" in s.signal_detail or s.signal_type == "scraped_job":
                pm_company_ids.add(s.company_id)
        for cid in pm_company_ids:
            db.update_yc_hiring_status(cid, is_hiring_pm=True)
        db.conn.commit()

        typer.echo(f"  Signals found: {len(signals)}")
        typer.echo(f"  Companies hiring PM: {len(pm_company_ids)}")

        # Show top results
        if pm_company_ids:
            typer.echo("\n  Companies with PM signals:")
            for cid in list(pm_company_ids)[:15]:
                c = db.get_yc_company_by_id(cid)
                if c:
                    typer.echo(f"    {c['batch']:5} {c['company_name']:30} {c.get('website', '')}")
    finally:
        db.close()


@app.command(name="yc-scrape-founders")
def yc_scrape_founders(
    batch: Optional[str] = typer.Option(None, "--batch", "-b", help="Filter by batch"),
    limit: int = typer.Option(0, "--limit", help="Max companies to scrape (0 = all)"),
    hiring_only: bool = typer.Option(False, "--hiring-only/--all", help="Only scrape hiring companies"),
    concurrency: int = typer.Option(10, "--concurrency", help="Concurrent requests"),
) -> None:
    """Scrape founder names, titles, LinkedIn & Twitter from YC website pages."""
    _configure_logging()
    asyncio.run(_run_yc_scrape_founders(batch, limit, hiring_only, concurrency))


async def _run_yc_scrape_founders(
    batch: Optional[str], limit: int, hiring_only: bool, concurrency: int,
) -> None:
    from storage.db import JobDB
    from yc_startups.founder_scraper import scrape_and_store_founders

    db = JobDB()
    try:
        companies = db.get_yc_companies(
            batch=batch or "",
            hiring_only=hiring_only,
            limit=limit,
        )
        if not companies:
            typer.echo("No companies match filters. Run yc-sync first.")
            return

        typer.echo(f"Scraping founders from {len(companies)} YC company pages...\n")
        stored = await scrape_and_store_founders(
            db, companies=companies, max_concurrent=concurrency, limit=limit,
        )
        stats = db.get_yc_stats()
        typer.echo(f"\nDone: {stored} founder contacts scraped and stored")
        typer.echo(f"Total founders in DB: {stats['total_founders']}")
    finally:
        db.close()


@app.command(name="yc-enrich-founders")
def yc_enrich_founders(
    batch: Optional[str] = typer.Option(None, "--batch", "-b", help="Filter by batch"),
    limit: int = typer.Option(50, "--limit", help="Max companies to enrich"),
    hiring_only: bool = typer.Option(True, "--hiring-only/--all", help="Only enrich hiring companies"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without calling Apollo"),
) -> None:
    """Enrich YC founder contacts with verified emails using Apollo (costs credits)."""
    _configure_logging()
    asyncio.run(_run_yc_enrich(batch, limit, hiring_only, dry_run))


async def _run_yc_enrich(
    batch: Optional[str], limit: int, hiring_only: bool, dry_run: bool,
) -> None:
    from storage.db import JobDB
    from yc_startups.enricher import enrich_yc_founders

    if not settings.APOLLO_API_KEY:
        typer.echo("APOLLO_API_KEY not set in .env — cannot enrich founders.", err=True)
        raise typer.Exit(1)

    db = JobDB()
    try:
        companies = db.get_yc_companies(
            batch=batch or "",
            hiring_only=hiring_only,
            limit=limit,
        )
        if not companies:
            typer.echo("No companies match filters. Try --all or sync first.")
            return

        typer.echo(f"Enriching founders for {len(companies)} YC companies"
                    f"{' (DRY RUN)' if dry_run else ''}...\n")

        enriched = await enrich_yc_founders(
            companies, settings, limit=limit, dry_run=dry_run,
        )

        if not dry_run:
            for contact in enriched:
                db.upsert_yc_founder_contact(contact)
            db.conn.commit()

        verified = sum(1 for e in enriched if e.get("founder_email_verified"))
        typer.echo(f"\nDone: {len(enriched)} founders enriched, {verified} verified emails")
    finally:
        db.close()


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind the dashboard server"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind (use 0.0.0.0 for LAN access)"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
) -> None:
    """Start the web dashboard server at http://localhost:<port>"""
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn not installed. Run: pip install fastapi 'uvicorn[standard]'", err=True)
        raise typer.Exit(1)
    typer.echo(f"\n  PMHunt Dashboard → http://{host}:{port}\n")
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
