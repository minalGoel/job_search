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
        """
        context = await self.bm.get_context(
            platform=self.name,
            cookies_dir=Path("cookies"),
        )
        page = await context.new_page()

        delay = random.uniform(2.0, 5.0)
        self._log.debug("page.delay", seconds=round(delay, 2), url=url)
        await asyncio.sleep(delay)

        await page.goto(url, wait_until="domcontentloaded")
        self._log.info("page.loaded", url=url)
        return page

    async def _safe_scrape(self) -> list[Job]:
        """Run :meth:`scrape` with error handling; return ``[]`` on failure."""
        try:
            self._log.info("scrape.start")
            jobs = await self.scrape()
            self._log.info("scrape.done", count=len(jobs))
            return jobs
        except Exception:
            self._log.exception("scrape.failed")
            return []
