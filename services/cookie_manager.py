from __future__ import annotations

from pathlib import Path

import structlog

from browser.context import BrowserManager

log = structlog.get_logger(__name__)

# Platform login URLs
LOGIN_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/login",
    "naukri": "https://www.naukri.com/nlogin/login",
    "iimjobs": "https://www.iimjobs.com/login",
    "cutshort": "https://cutshort.io/login",
    "instahyre": "https://www.instahyre.com/login/",
    "wellfound": "https://wellfound.com/login",
    "indeed": "https://secure.indeed.com/auth",
    "glassdoor": "https://www.glassdoor.co.in/profile/login_input.htm",
    "foundit": "https://www.foundit.in/login",
    "hirist": "https://www.hirist.tech/login",
    "weekday": "https://www.weekday.works/login",
}


async def interactive_login(platform: str, cookies_dir: Path) -> bool:
    """Open a headed browser for manual login, then save cookies.

    Returns True if cookies were saved successfully.
    """
    login_url = LOGIN_URLS.get(platform)
    if not login_url:
        log.error("cookie_manager.unknown_platform", platform=platform)
        return False

    cookies_dir.mkdir(parents=True, exist_ok=True)

    async with BrowserManager(headless=False) as bm:
        context = await bm.get_context(platform, cookies_dir)
        page = await context.new_page()
        await page.goto(login_url)

        print(f"\n  A browser window has opened to {login_url}")
        print(f"  Please log in to {platform} manually.")
        input("  Press ENTER here once you are logged in... ")

        await bm.save_cookies(platform, context, cookies_dir)
        log.info("cookie_manager.login_saved", platform=platform)
        print(f"  Cookies saved for {platform}.\n")
        return True


def has_cookies(platform: str, cookies_dir: Path) -> bool:
    """Check if saved cookies exist for a platform."""
    return (cookies_dir / f"{platform}.json").exists()
