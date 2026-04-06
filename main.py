from __future__ import annotations

import asyncio
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
                    jobs = await task
                    if jobs:
                        inserted_jobs: list[Job] = []
                        skipped = 0
                        for job in jobs:
                            if db.insert_job(job):
                                inserted_jobs.append(job)
                            else:
                                skipped += 1

                        all_new_jobs.extend(inserted_jobs)
                        typer.echo(f"  {name}: {len(inserted_jobs)} new, {skipped} existing")
                    else:
                        typer.echo(f"  {name}: 0 results")
                except Exception as e:
                    errors[name] = str(e)
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

    typer.echo("Scanning VC portfolio job portals...\n")

    async with BrowserManager() as bm:
        scraper = VCPortalScraper(bm)
        jobs = await scraper.scrape_all()

    if jobs:
        db = JobDB()
        try:
            inserted, skipped = db.insert_jobs(jobs)
            typer.echo(f"\nVC portals: {inserted} new, {skipped} existing")
            settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            export_csv([j.model_dump() for j in jobs], settings.OUTPUT_DIR)
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

    typer.echo("Scanning US MNC career pages...\n")

    async with BrowserManager() as bm:
        scraper = MNCCareerScraper(bm)
        jobs = await scraper.scrape_all()

    if jobs:
        db = JobDB()
        try:
            inserted, skipped = db.insert_jobs(jobs)
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


if __name__ == "__main__":
    app()
