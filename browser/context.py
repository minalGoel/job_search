from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from playwright.async_api import (
    BrowserContext,
    async_playwright,
)
from playwright_stealth import Stealth

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

log = structlog.get_logger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


class BrowserManager:
    """Manages a shared Playwright browser instance and per-platform contexts."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the Playwright Chromium browser."""
        log.info("browser.starting", headless=self._headless)
        self._playwright = await async_playwright().start()
        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--disable-gpu",
            "--window-size=1280,800",
            "--disable-extensions",
            "--disable-infobars",
        ]
        if self._headless:
            # Use Chrome's new headless mode: launch as "headed" but pass --headless=new.
            # This is much harder for Akamai/bot-detection to identify vs the old headless mode.
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=base_args + ["--headless=new"],
            )
        else:
            # Headed mode (used for manual logins): show a real browser window
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=base_args,
            )
        log.info("browser.started")

    async def stop(self) -> None:
        """Close all contexts, the browser, and stop Playwright."""
        for name, ctx in self._contexts.items():
            log.debug("browser.context.closing", platform=name)
            await ctx.close()
        self._contexts.clear()

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        log.info("browser.stopped")

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    async def get_context(
        self,
        platform: str,
        cookies_dir: Path,
    ) -> BrowserContext:
        """Return a stealth BrowserContext for *platform*, reusing if cached.

        If ``cookies_dir/{platform}.json`` exists the storage state is loaded
        so that previous session cookies / local-storage are restored.
        """
        if platform in self._contexts:
            return self._contexts[platform]

        if self._browser is None:
            raise RuntimeError("BrowserManager has not been started — call start() first")

        user_agent = random.choice(_USER_AGENTS)
        storage_path = cookies_dir / f"{platform}.json"

        kwargs: dict = {
            "user_agent": user_agent,
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
        }
        if storage_path.exists():
            kwargs["storage_state"] = str(storage_path)
            log.info("browser.context.restoring_cookies", platform=platform)

        context = await self._browser.new_context(**kwargs)

        # playwright-stealth API migration (v2+): method is apply_stealth (async).
        # Older releases exposed apply_stealth_async / stealth_async. Try each.
        stealth = Stealth()
        apply_fn = (
            getattr(stealth, "apply_stealth", None)
            or getattr(stealth, "apply_stealth_async", None)
        )
        if apply_fn is None:
            log.warning("stealth.no_apply_method", note="playwright-stealth API changed")
        else:
            try:
                result = apply_fn(context)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                log.exception("stealth.apply_failed", platform=platform)

        self._contexts[platform] = context
        log.info("browser.context.created", platform=platform, user_agent=user_agent)
        return context

    async def save_cookies(
        self,
        platform: str,
        context: BrowserContext,
        cookies_dir: Path,
    ) -> None:
        """Persist the browser context's storage state to disk."""
        cookies_dir.mkdir(parents=True, exist_ok=True)
        storage_path = cookies_dir / f"{platform}.json"
        await context.storage_state(path=str(storage_path))
        log.info("browser.cookies.saved", platform=platform, path=str(storage_path))

    # ------------------------------------------------------------------
    # Async context-manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.stop()
