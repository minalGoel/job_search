"""Pre-flight checks that decide whether a scraper can run at all.

Pure functions — no Playwright, no DB, no network — so the orchestrator's
skip logic is unit-testable without ``_run_all``.

A scraper is *skipped* (not failed) when its configuration is incomplete:
login-gated platform without saved cookies, or an API-key-based aggregator
whose key is blank. Skips are recorded in ``runs.errors`` with the
``SKIP_PREFIX`` so every consumer (CLI ``status``, ``/api/runs``, dashboard)
can tell them apart from real errors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

SKIP_PREFIX = "skipped: "


def has_cookies(platform: str, cookies_dir: Path) -> bool:
    """Check if saved cookies exist for a platform."""
    return (cookies_dir / f"{platform}.json").exists()


def skip_reason(scraper_cls: Any, settings: Any, cookies_dir: Path) -> str | None:
    """Return a human-readable reason this scraper cannot run, or ``None``."""
    if getattr(scraper_cls, "requires_login", False) and not has_cookies(scraper_cls.name, cookies_dir):
        return f"no cookies — run `python main.py login {scraper_cls.name}`"
    missing = [k for k in getattr(scraper_cls, "required_settings", ()) if not getattr(settings, k, "")]
    if missing:
        return f"missing API key ({', '.join(missing)}) — set in .env"
    return None


def needs_browser(scraper_classes: Iterable[Any]) -> bool:
    """True if any of the given scraper classes needs Chromium."""
    return any(getattr(cls, "uses_browser", True) for cls in scraper_classes)


def partition(
    names: Iterable[str],
    registry: Mapping[str, Any],
    settings: Any,
    cookies_dir: Path,
) -> tuple[list[str], dict[str, str], list[str]]:
    """Split requested platform names into ``(runnable, skipped, unknown)``.

    ``skipped`` maps name -> ``"skipped: <reason>"`` (already prefixed, ready
    to be stored in ``runs.errors``).
    """
    runnable: list[str] = []
    skipped: dict[str, str] = {}
    unknown: list[str] = []
    for name in names:
        cls = registry.get(name)
        if cls is None:
            unknown.append(name)
            continue
        reason = skip_reason(cls, settings, cookies_dir)
        if reason:
            skipped[name] = f"{SKIP_PREFIX}{reason}"
        else:
            runnable.append(name)
    return runnable, skipped, unknown


def is_skip_note(note: str | None) -> bool:
    return bool(note) and str(note).startswith(SKIP_PREFIX)


def split_run_notes(errors: Mapping[str, str] | None) -> tuple[dict[str, str], dict[str, str]]:
    """Split a ``runs.errors`` dict into ``(errors, skipped)``.

    ``skipped`` values have the prefix removed.
    """
    real: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for name, note in (errors or {}).items():
        if is_skip_note(note):
            skipped[name] = str(note)[len(SKIP_PREFIX):]
        else:
            real[name] = str(note)
    return real, skipped
