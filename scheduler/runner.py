from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import Settings

log = structlog.get_logger(__name__)


async def _run_scrape_cycle() -> None:
    """Import and run a full scrape cycle. Imported lazily to avoid circular deps."""
    from main import _run_all
    await _run_all()


def start_scheduler(settings: Settings) -> None:
    """Start the APScheduler daemon with configured cron + optional polling."""
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    # Add cron jobs for each configured time (e.g. 09:00, 16:00)
    for hour, minute in settings.schedule_times_parsed:
        trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Kolkata")
        scheduler.add_job(_run_scrape_cycle, trigger, id=f"cron_{hour:02d}{minute:02d}")
        log.info("scheduler.cron_added", hour=hour, minute=minute)

    # Optional interval polling
    if settings.POLL_INTERVAL_MINUTES > 0:
        trigger = IntervalTrigger(minutes=settings.POLL_INTERVAL_MINUTES)
        scheduler.add_job(_run_scrape_cycle, trigger, id="poll")
        log.info("scheduler.poll_added", interval_minutes=settings.POLL_INTERVAL_MINUTES)

    scheduler.start()
    log.info("scheduler.started")

    # Keep the event loop running
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("scheduler.stopped")
