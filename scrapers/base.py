from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import structlog
from playwright.async_api import Page

from models.job import Job

if TYPE_CHECKING:
    from browser.context import BrowserManager
    from config.settings import Settings

log = structlog.get_logger(__name__)


class ScraperSkipped(Exception):
    """Raised when a scraper cannot run because of *configuration*, not failure.

    Examples: login-gated platform with no saved cookies, aggregator with no
    API key, API key rejected with 401/403. ``_safe_scrape`` turns this into a
    ``"skipped: ..."`` note instead of an error so the run is not marked red.
    """


class BaseScraper(ABC):
    """Abstract base class that every platform scraper must extend."""

    name: str = ""  # e.g. "linkedin", "naukri"
    requires_login: bool = False
    # False for pure-httpx scrapers so the orchestrator can skip launching
    # Chromium when no browser-based scraper is selected.
    uses_browser: bool = True
    # Settings attribute names that must be non-empty for this scraper to run
    # (e.g. ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")). Checked by preflight.
    required_settings: tuple[str, ...] = ()

    def __init__(
        self,
        browser_manager: Optional[BrowserManager],
        search_params: Any,
        settings: Optional[Settings] = None,
    ) -> None:
        if settings is None:
            from config.settings import Settings as _Settings

            settings = _Settings()
        self.bm = browser_manager
        self.search_params = search_params
        self.settings = settings
        # Absolute path — never the CWD-relative Path("cookies") (see
        # known_edge_cases.md: cookies/.env were resolved relative to CWD).
        self.cookies_dir: Path = settings.COOKIES_DIR
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

    def _require_settings(self) -> None:
        """Raise ``ScraperSkipped`` if any ``required_settings`` value is blank."""
        missing = [k for k in self.required_settings if not getattr(self.settings, k, "")]
        if missing:
            raise ScraperSkipped(f"missing API key ({', '.join(missing)}) — set in .env")

    async def _get_page(self, url: str) -> Page:
        """Open a new page in this platform's browser context.

        Adds a random delay (2-5 s) before navigation to reduce
        fingerprinting risk, then waits for the network to settle.
        On navigation failure the page is closed before re-raising
        so we never leak pages/contexts.
        """
        if self.bm is None:
            raise RuntimeError(
                f"{self.name}: uses_browser=False scraper called _get_page(); "
                "set uses_browser=True or use httpx"
            )
        context = await self.bm.get_context(
            platform=self.name,
            cookies_dir=self.cookies_dir,
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

        A ``ScraperSkipped`` is reported as ``"skipped: <reason>"`` (a
        configuration state, not an error) with a single warning and no
        traceback.
        """
        try:
            self._log.info("scrape.start")
            jobs = await self.scrape()
            self._log.info("scrape.done", count=len(jobs))
            return jobs, None
        except ScraperSkipped as exc:
            self._log.warning("scrape.skipped", reason=str(exc))
            return [], f"skipped: {exc}"
        except Exception as exc:
            self._log.exception("scrape.failed")
            return [], f"{type(exc).__name__}: {exc}"
