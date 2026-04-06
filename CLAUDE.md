# CLAUDE.md — Job Search Aggregator

## Project Overview

A Python CLI tool that aggregates Senior Product Manager roles from 14 job platforms, scans VC portfolio job boards, US MNC career pages, tracks recently funded Indian startups, and runs automated outreach campaigns. Designed for a PM job seeker targeting Delhi NCR, 5-7 years experience, 40+ LPA, Tech/SaaS/B2B.

## Architecture

```
job_search/
├── main.py                        # Typer CLI entrypoint (all commands below)
├── config/
│   ├── __init__.py
│   ├── settings.py                # Pydantic-settings: SMTP, Apollo, Gmail, schedule, paths (loads .env)
│   └── search_params.py           # SearchParams dataclass: titles, location, experience, CTC
├── models/
│   ├── __init__.py
│   └── job.py                     # Pydantic Job model (shared by all scrapers), auto-computed id + dedup_hash
├── scrapers/
│   ├── __init__.py                # SCRAPER_REGISTRY dict mapping name -> class (14 scrapers)
│   ├── base.py                    # Abstract BaseScraper: _get_page(), _safe_scrape()
│   ├── naukri.py                  # XHR JSON API interception + HTML fallback
│   ├── iimjobs.py                 # Server-rendered HTML
│   ├── foundit.py                 # JSON API interception + HTML fallback
│   ├── indeed.py                  # HTML scraping with stealth
│   ├── cutshort.py                # React SPA, XHR interception, login-gated
│   ├── wellfound.py               # React SPA, Playwright render
│   ├── linkedin.py                # Guest search, stealth, max 3 pages, auth-wall detection
│   ├── instahyre.py               # Login-gated, cookie-based, session expiry detection
│   ├── glassdoor.py               # BEST EFFORT (Cloudflare), graceful degradation
│   ├── hirist.py                  # HTML scraping (sister of IIMJobs)
│   ├── remoteok.py                # Free JSON API (httpx, no Playwright needed)
│   ├── weworkremotely.py          # RSS feed parsing (httpx + xml.etree, no Playwright)
│   ├── ycombinator.py             # YC public job listing pages
│   └── weekday.py                 # Login-gated SPA, API interception
├── browser/
│   ├── __init__.py
│   └── context.py                 # BrowserManager: Playwright + stealth, per-platform contexts, cookie persistence
├── services/
│   ├── __init__.py
│   ├── cookie_manager.py          # Interactive login flow, LOGIN_URLS dict, cookie health check
│   ├── dedup.py                   # Cross-platform duplicate marking via dedup_hash
│   ├── exporter.py                # CSV per-run + cumulative Excel (openpyxl) with conditional formatting
│   └── notifier.py                # SMTP email alerts for new jobs + session expiry warnings
├── storage/
│   ├── __init__.py
│   └── db.py                      # SQLite: jobs table, runs table, dedup_hash index
├── scheduler/
│   ├── __init__.py
│   └── runner.py                  # APScheduler: 9 AM + 4 PM IST cron, optional polling
├── funding/
│   ├── __init__.py
│   ├── models.py                  # FundedCompany dataclass
│   ├── scanner.py                 # Scrapes Inc42, YourStory, Entrackr, VCCircle + LinkedIn cross-reference
│   └── exporter.py                # Funding-specific CSV + Excel export
├── vc_portals/
│   ├── __init__.py
│   ├── registry.py                # 30 Indian VCs with metadata, 9 with known job portal URLs
│   └── scraper.py                 # Scrapes VC job portals for PM roles
├── mnc_careers/
│   ├── __init__.py
│   ├── registry.py                # 42 US MNCs with Delhi NCR offices + career page URLs
│   └── scraper.py                 # Scrapes MNC career pages for PM roles
├── outreach/
│   ├── __init__.py
│   ├── models.py                  # Pydantic models: Contact, OutreachEmail, CreditUsage
│   ├── db.py                      # Separate SQLite DB (output/outreach.db): contacts, emails, credits tables
│   ├── apollo_client.py           # Apollo.io API: People Search + People Enrich (2-step)
│   ├── prospeo_client.py          # Prospeo API: email finder fallback when Apollo misses
│   ├── enricher.py                # Job listings + funded companies -> Apollo Search -> Enrich -> verified emails
│   ├── templates.py               # 3-step email sequence: intro, day 3 follow-up, day 7 final
│   ├── reviewer.py                # Localhost HTTP server (port 8899) with approve/edit/skip/snooze UI
│   ├── gmail_sender.py            # Gmail API OAuth2, 25/day rate limit, thread-aware follow-ups
│   └── pipeline.py                # Orchestrates enrich -> template -> review -> send -> track
├── output/                        # Runtime: jobs.db, outreach.db, CSV/Excel exports (gitignored)
├── .env.example                   # Template for SMTP, Apollo, Gmail, schedule, logging config
├── requirements.txt               # Python dependencies
├── AGENTS.md                      # Agent instructions
└── .gitignore                     # Excludes .venv, output/, cookies/, logs/, credentials/, .env
```

## Key Patterns

- **`from __future__ import annotations`** is used in every file for Python 3.9 compatibility
- **All scrapers** extend `BaseScraper` (scrapers/base.py) and implement `async def scrape() -> list[Job]`
- **SCRAPER_REGISTRY** in `scrapers/__init__.py` maps platform names to scraper classes -- add new scrapers here
- **Job model** (models/job.py) auto-computes `id` (SHA256 hash) and has a `dedup_hash` property for cross-platform matching
- **Browser contexts** are per-platform with separate cookie jars via `BrowserManager.get_context(platform, cookies_dir)`
- **Playwright stealth** uses `playwright_stealth.Stealth().apply_stealth(context)` (v2 API, NOT `stealth_async`)
- **Async everywhere**: all scrapers, browser ops, and the main pipeline use asyncio
- **Error isolation**: each scraper runs in its own try/except via `_safe_scrape()`, failures don't cascade
- **Two SQLite databases**: `output/jobs.db` (jobs + runs) and `output/outreach.db` (contacts + emails + credits)

## CLI Commands

```bash
source .venv/bin/activate

# Job scraping
python main.py run                          # Scrape all 14 platforms
python main.py run -p naukri -p linkedin    # Specific platforms only
python main.py login instahyre             # Headed browser for manual login
python main.py schedule                     # Start 9AM/4PM IST daemon
python main.py export                       # Re-export DB to CSV/Excel
python main.py status                       # Last run + cookie health

# Supplementary sources
python main.py funding                      # Scan funding news + LinkedIn check
python main.py vc-jobs                      # Scrape VC portfolio job boards
python main.py mnc-jobs                     # Scrape US MNC career pages
python main.py run-all                      # Everything in sequence

# Outreach pipeline
python main.py outreach-enrich              # Apollo enrichment -> email drafts
python main.py outreach-review              # Browser review page (localhost:8899)
python main.py outreach-send                # Send approved emails via Gmail API
python main.py outreach-status              # Pipeline stats + credit usage
python main.py outreach-reply CONTACT_ID    # Mark reply, cancel follow-ups
```

## Outreach System

The `outreach/` module implements a 5-step automated outreach pipeline:

1. **Enrich** (`enricher.py`): Feeds from job listings + funded companies -> Apollo People Search (find contacts, no emails returned) -> Apollo People Enrich (get verified email) -> Prospeo fallback if Apollo misses
2. **Template** (`templates.py`): 3-step email sequence with variable substitution -- intro, day 3 follow-up, day 7 final
3. **Review** (`reviewer.py`): Localhost HTTP server on port 8899 with approve/edit/skip/snooze buttons
4. **Send** (`gmail_sender.py`): Gmail API OAuth2, 25/day rate limit, thread-aware follow-ups
5. **Track** (`db.py`): Separate SQLite DB with contacts, emails, and credit tracking tables

Key rules:
- **Two-step Apollo flow**: People Search returns contacts without emails; People Enrich is a separate call to get verified emails. This is intentional (Apollo charges differently for each).
- **One-per-company rule**: Normalized company name dedup ensures only one contact per company enters the pipeline.
- **Prospeo fallback**: When Apollo Enrich fails to find an email, `prospeo_client.py` is used as a secondary source.
- **Gmail credentials**: OAuth2 via `credentials/gmail_credentials.json` from Google Cloud Console; token auto-refreshed at runtime.

## Development

- **Python 3.9.6** (system), venv at `.venv/`
- **Dependencies**: `pip install -r requirements.txt && playwright install chromium`
- **Config**: copy `.env.example` to `.env` and fill in SMTP, Apollo, Gmail, and Prospeo credentials
- **Storage**: SQLite at `output/jobs.db` and `output/outreach.db`, CSV/Excel exports in `output/`
- **Cookies**: Playwright storage state in `cookies/{platform}.json`
- **Logging**: structlog to console (configurable via LOG_LEVEL in .env)

## Adding a New Scraper

1. Create `scrapers/newplatform.py` extending `BaseScraper`
2. Set `name = "newplatform"` and `requires_login = True/False`
3. Implement `async def scrape(self) -> list[Job]`
4. Register in `scrapers/__init__.py` SCRAPER_REGISTRY
5. If login-gated, add login URL to `services/cookie_manager.py` LOGIN_URLS

## Important Notes

- LinkedIn and Glassdoor have aggressive anti-scraping; expect partial results or failures
- RemoteOK and WeWorkRemotely use API/RSS (no Playwright needed) -- fastest scrapers
- Scraper selectors (CSS) will break when sites redesign -- check logs for `0 results` patterns
- Never commit `.env`, `cookies/`, or `credentials/` (contains credentials and session tokens)
- The `from __future__ import annotations` import is required everywhere for Python 3.9 compatibility
- Playwright stealth is v2 API: `Stealth().apply_stealth(context)` -- do NOT use the old `stealth_async` function
