from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from playwright.async_api import Page

from models.job import Job

if TYPE_CHECKING:
    from browser.context import BrowserManager

log = structlog.get_logger(__name__)


class BaseScraper(ABC):
    """Abstract base class that every platform scraper must extend."""

    name: str = ""  # e.g. "linkedin", "naukri"
    requires_login: bool = False

    def __init__(
        self,
        browser_manager: BrowserManager,
        search_params: Any,
    ) -> None:
        self.bm = browser_manager
        self.search_params = search_params
        self._log = log.bind(scraper=self.name)

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self) -> list[Job]:
        """Scrape job listings and return a list of Job models."""
        ...

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_page(self, url: str) -> Page:
        """Open a new page in this platform's browser context.

        Adds a random delay (2-5 s) before navigation to reduce
        fingerprinting risk, then waits for the network to settle.
        On navigation failure the page is closed before re-raising
        so we never leak pages/contexts.
        """
        context = await self.bm.get_context(
            platform=self.name,
            cookies_dir=Path("cookies"),
        )
        page = await context.new_page()

        delay = random.uniform(2.0, 5.0)
        self._log.debug("page.delay", seconds=round(delay, 2), url=url)
        await asyncio.sleep(delay)

        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception:
            try:
                await page.close()
            except Exception:
                pass
            raise
        self._log.info("page.loaded", url=url)
        return page

    async def _safe_scrape(self) -> tuple[list[Job], str | None]:
        """Run :meth:`scrape` with error handling.

        Returns a tuple of ``(jobs, error_message)`` where ``error_message``
        is ``None`` on success or the exception string on failure.
        This lets the orchestrator record the true error per platform
        instead of silently swallowing it.
        """
        try:
            self._log.info("scrape.start")
            jobs = await self.scrape()
            self._log.info("scrape.done", count=len(jobs))
            return jobs, None
        except Exception as exc:
            self._log.exception("scrape.failed")
            return [], f"{type(exc).__name__}: {exc}"
