# AGENTS.md — Agent Guidelines for Job Search Aggregator

## Project Context

This is a Python async CLI tool for aggregating PM job listings across 14 platforms, VC portals, MNC career pages, funding trackers, and automated email outreach. The user is a Senior PM candidate targeting Delhi NCR, 5-7 yrs exp, 40+ LPA, Tech/SaaS/B2B.

## Agent Roles

### Scraper Development Agent
**When to use**: Adding or fixing a platform scraper.

**Key files to read first**:
- `scrapers/base.py` — the abstract base class all scrapers extend
- `scrapers/__init__.py` — the SCRAPER_REGISTRY (must register new scrapers here)
- `models/job.py` — the Job Pydantic model (all scrapers must return `list[Job]`)
- `config/search_params.py` — SearchParams dataclass with titles, location, experience, CTC
- `services/cookie_manager.py` — LOGIN_URLS dict (add here if login-gated)

**Patterns to follow**:
- Extend `BaseScraper`, set `name` and `requires_login` class attributes
- Use `self._get_page(url)` for Playwright navigation (adds stealth + delays)
- Use `self._log` (structlog) for all logging
- Use BeautifulSoup for HTML parsing, `await page.content()` to get HTML
- For SPAs: `await page.wait_for_selector(...)` before parsing
- For API-based scrapers (like RemoteOK): use `httpx.AsyncClient`, no Playwright needed
- Always close pages after use: `await page.close()`
- Handle errors per-card (try/except inside the loop), log and continue
- Parse relative dates ("2 days ago") with a `_parse_relative_date()` helper
- **Never hardcode search queries** — always use `self.search_params.title_keywords[0]` so the scraper respects SearchParams
- **Guard `_get_page` failures**: wrap `page.goto()` in try/except and call `await page.close()` before re-raising, to prevent browser resource leaks

**Anti-scraping considerations**:
- LinkedIn: guest mode, 3-7s delays, max 3 pages, check for `authwall` redirect
- Glassdoor: best-effort only, check for `challenge`/`captcha` in HTML, return empty on block
- General: random delays via `asyncio.sleep(random.uniform(2, 5))`

### Funding Scanner Agent
**When to use**: Modifying or extending the funding news scraper.

**Key files**:
- `funding/scanner.py` — FundingScanner class with per-source methods
- `funding/models.py` — FundedCompany dataclass
- `funding/exporter.py` — CSV + Excel export for funded companies

**Patterns**: Each source is a separate `_scan_*()` async method. All run concurrently via `asyncio.gather()`. Company extraction from headlines uses regex pattern matching. SERIES_KEYWORDS list must have "pre-seed"/"pre-series" before "seed" to avoid partial matches.

### Registry/Data Agent
**When to use**: Updating VC fund data, MNC lists, or job portal registries.

**Key files**:
- `vc_portals/registry.py` — 30 VCFund dataclass instances with portal URLs
- `mnc_careers/registry.py` — 42 MNC dataclass instances with career page URLs
- `services/cookie_manager.py` — LOGIN_URLS dict

### Service Agent
**When to use**: Modifying dedup logic, email notifications, export format, or scheduling.

**Key files**:
- `services/dedup.py` — Cross-platform dedup via `dedup_hash` (SHA256 of normalized company + title)
- `services/notifier.py` — SMTP email with HTML table + CSV attachment (uses `html.escape()` for all user data)
- `services/exporter.py` — CSV per-run + master Excel with conditional formatting
- `scheduler/runner.py` — APScheduler with CronTrigger (9 AM, 4 PM IST)

### Outreach Agent
**When to use**: Modifying the outreach pipeline — contact enrichment, email templates, review UI, Gmail sending, or follow-up logic.

**Key files to read first**:
- `outreach/pipeline.py` — Main orchestration: enrich → template → review → send → track
- `outreach/db.py` — Separate SQLite DB (`output/outreach.db`) with contacts, emails, credits tables
- `outreach/models.py` — `OutreachContact` and `OutreachEmail` Pydantic models
- `outreach/enricher.py` — Company → Apollo Search → Apollo Enrich → verified emails

**Apollo API (2-step process)**:
1. **People Search** (`/api/v1/mixed_people/api_search`) — finds contacts at a company by title. Does NOT return emails.
2. **People Enrichment** (`/api/v1/people/match`) — takes name + company, returns verified email. Requires `reveal_personal_emails: true`.
- Auth: `x-api-key` header
- Free tier: 10K credits/year (~833/month), 600 API calls/day
- Rate limiting: `APOLLO_RATE_LIMIT_PER_MINUTE` in settings

**Prospeo fallback** (`outreach/prospeo_client.py`):
- Endpoint: `POST https://api.prospeo.io/api/v1/enrich-person`
- Auth: Bearer token
- 75 free credits/month
- Used only when Apollo returns no email for a contact

**Contact priority by company size**:
- Startup (<100): Founder → Product Leader → Recruiter
- Mid-size (100-500): Product Leader → Recruiter → Founder
- Enterprise (500+): Recruiter → Product Leader

**One-per-company rule**: `company_has_outreach()` checks normalized company name. Skip if any contact exists in status other than "skipped".

**Email templates** (`outreach/templates.py`):
- 3-step sequence: intro (Day 1), follow-up (Day 3), final (Day 7)
- Uses `string.Template` with `${}` variables
- Key variables: `${first_name}`, `${company}`, `${job_title}`, `${funding_context}`, `${sender_name}`
- `${funding_context}` is conditionally injected only for funded company sources

**Review UI** (`outreach/reviewer.py`):
- Localhost HTTP server on port 8899 (`REVIEW_PORT`)
- HTML page with JS fetch() calls → POST /action endpoint
- Actions: approve, edit (saves to DB then needs separate approve), skip, snooze
- Handler class: `ReviewHandler` with class-level `db` and `html_content` attributes

**Gmail sending** (`outreach/gmail_sender.py`):
- Uses `google-api-python-client` with OAuth2
- Credentials: `credentials/gmail_credentials.json` + `credentials/gmail_token.json`
- Thread-aware: follow-ups include `threadId` from step 1's response
- Daily limit enforced by `get_today_send_count()` in OutreachDB

### Pipeline/CLI Agent
**When to use**: Modifying the main orchestration logic or adding CLI commands.

**Key files**:
- `main.py` — Typer CLI with all commands, `_run_all()` orchestrates scrape → dedup → export → notify
- `config/settings.py` — Pydantic-settings loading from .env

**CLI command map (14 commands)**:
- `run`, `schedule`, `login`, `export`, `status` — core job scraping
- `funding`, `vc-jobs`, `mnc-jobs`, `run-all` — supplementary sources
- `outreach-enrich`, `outreach-review`, `outreach-send`, `outreach-status`, `outreach-reply` — outreach pipeline

## Common Pitfalls

1. **playwright_stealth API**: v2 uses `Stealth().apply_stealth(context)`, NOT `stealth_async(context)`
2. **Python 3.9 compatibility**: Use `from __future__ import annotations` in every file for `X | Y` type unions
3. **Import paths**: Project uses absolute imports from project root (e.g., `from models.job import Job`). `sys.path.insert(0, project_root)` is set in main.py.
4. **Cookie paths**: Use `Path("cookies")` relative path in scrapers — the BrowserManager resolves it relative to CWD
5. **SQLite thread safety**: `JobDB` and `OutreachDB` each use a single connection; don't share across threads (asyncio is fine since it's single-threaded)
6. **Selector fragility**: CSS selectors in scrapers WILL break when sites update. Use multiple fallback selectors with `or` chains: `soup.select("div.new-class") or soup.select("div.old-class")`
7. **Two separate databases**: Jobs in `output/jobs.db` (via `storage/db.py`), outreach in `output/outreach.db` (via `outreach/db.py`). Don't mix them.
8. **Apollo Search vs Enrich**: Search does NOT return emails. Always follow up with Enrich endpoint for each contact.
9. **HTML escaping**: Use `html.escape()` for all user-supplied data in HTML output (reviewer, notifier).
10. **Search query**: Each scraper must pass `self.search_params.title_keywords[0]` as the search term — never a hardcoded string. Hardcoding silently ignores user config.
11. **Contact name extraction**: Use `.strip()` before `.split()[0]` when extracting first name from contact names — whitespace-only strings will cause IndexError otherwise.

## Testing Approach

- **Smoke test**: `python main.py run -p remoteok` (API-based, no browser needed, fastest feedback)
- **Browser test**: `python main.py run -p naukri` (Playwright + HTML parsing)
- **Login test**: `python main.py login instahyre` (headed browser, manual login)
- **Full test**: `python main.py run-all` (all sources)
- **Outreach test**: `python main.py outreach-status` (verify DB + credit tracking)
- **Import check**: `python -c "from scrapers import SCRAPER_REGISTRY; print(len(SCRAPER_REGISTRY))"`
- **Outreach import check**: `python -c "from outreach.pipeline import run_enrich, run_send"`

## File Organization Rules

- One scraper per file in `scrapers/`
- All scrapers registered in `scrapers/__init__.py` SCRAPER_REGISTRY
- Data registries (VCs, MNCs) are separate from their scrapers
- Services are stateless functions/classes (except JobDB/OutreachDB which hold connections)
- Outreach has its own DB, models, and pipeline — separate from the scraping pipeline
- Credentials go in `credentials/` (gitignored), API keys go in `.env` (gitignored)
- No test files yet — add to `tests/` directory when needed
