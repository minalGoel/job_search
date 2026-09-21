# PM Job Search Aggregator

An async Python CLI + web dashboard for aggregating Senior Product Manager roles across 14 job platforms (11 boards + 3 API aggregators), VC portfolios, ~350 MNC careers portals, YC companies, and real-time funding signals. **Deduplicates listings, scores jobs with heuristic + company-quality + warmth + semantic signals, tracks applications, and automates outreach via Apollo + Gmail.**

**Designed for:** PM candidates targeting Delhi NCR, 5–7 years experience, AI/Tech/SaaS/B2B roles.

---

## Features

### 🔍 Job Aggregation (14 active platforms)

Concurrent scrapers for:
- **Job Boards**: Naukri, IIMJobs, Hirist, Foundit, Indeed, LinkedIn (guest), RemoteOK, Instahyre*, Cutshort*, Weekday*
- **API aggregators**: Adzuna, Jooble, Careerjet (free API keys — skipped until set in `.env`)
- **Startup Listings**: YCombinator (Wellfound and Glassdoor are disabled — Cloudflare)

\* login-gated: skipped cleanly until you run `python main.py login <platform>`.

**All filtering is ours.** Every source is fetched broadly and then filtered in memory by `services/title_filter.py` (configurable keywords, exclusions and typo-tolerant fuzzy matching in `config/search_params.py`) and `services/location_filter.py`. Portal search parameters are only a volume pre-filter.

- **Titles**: anything containing "product" is kept; the dashboard's *title category* filter (PM / Leadership / Owner / Marketing / Design / Analyst-Ops / Eng / Other) sorts them and scoring demotes the non-PM families.
- **Locations**: a posting is kept if it mentions Delhi NCR — Gurgaon (any spelling), Noida, Delhi, Faridabad, Ghaziabad — or is remote/India-wide, even alongside other cities; it is dropped only when it names *other* locations exclusively. Remote and hybrid roles get a scoring bonus and a *work mode* filter.

### 💼 Supplementary Sources

- **VC Portals**: Scrapes job pages from 30+ VC funds
- **MNC Careers**: ~350 multinational careers portals via typed ATS fetchers (Workday, Greenhouse, Lever, SmartRecruiters, SuccessFactors classic + Unify, Phenom, Radancy, Oracle HCM, Avature, Amazon) plus a Playwright lane for the rest. Fetches each company's **full listing** and filters locally; per-company outcomes land in `source_runs` and the dashboard's *MNC Careers* screen. `python main.py mnc-discover` finds and verifies portals for new companies. The dashboard's **Companies** screen (`http://localhost:8000/#companies`) lists every registry company with website / LinkedIn / careers-portal links and what happened on the last extraction, so portals we can't scrape can be opened by hand.
- **YC Startups Module**: Syncs YC directory, detects hiring signals, enriches founder/company data
- **Funding Scanner**: Tracks recently funded companies from news sources (TechCrunch, Inc42, YC Batch pages)

### 🧠 Intelligent Scoring Engine

Jobs ranked by a **4-factor composite score**:

| Factor | Weight | Details |
|--------|--------|---------|
| **Relevance** | 45% | Title match + PM keywords + location + recency |
| **Salary Likelihood** | 30% | Known high-pay companies + MNC flag + funding series + seniority indicators |
| **Warmth** | 15% | LinkedIn connection proximity (requires imported CSV) |
| **Company Quality** | 10% | MNC presence + funding status + multiple PM roles + careers page |

**Latest: Semantic Similarity** (6th dimension) — sentence-transformers embedding distance between job description and candidate profile.

### 🔗 Connection Matching

- Import LinkedIn connection CSV to identify **warmth** (direct connection, 1st/2nd degree)
- Automatically scores jobs by network proximity
- Detects mutual connections for outreach context

### 📊 Decision Engine

- **Recommender**: Rank jobs by priority bucket (high/medium/low/unscored)
- **Company Intel**: Enriches company profiles with MNC status, funding data, and VC affiliation
- **Deduplication**: Cross-platform duplicate detection via normalized company + title hash
- **Scoring Dashboard**: View top N jobs by bucket, rescore on-demand, batch tag jobs

### 📮 Outreach Pipeline

End-to-end **contact enrichment + templated drafts + local review + Gmail sending**:

1. **Enrichment**: Apollo API search (job title) + enrichment (email verification), fallback to Prospeo
2. **Contact Priority**: Founder > Product Leader > Recruiter (for startups); Recruiter > PM > Founder (for enterprises)
3. **Templates**: 3-step sequence — intro (Day 1), follow-up (Day 3), final (Day 7)
4. **Review UI**: Local HTTP server (port 8899) with approve/edit/skip/snooze actions
5. **Sending**: Gmail API with threading support, daily limits, bounce tracking

### 📱 Web Dashboard

- **FastAPI + SPA** serving REST API + WebSocket streams
- **Live job browser** with filters, search, and sorting
- **Outreach status** dashboard showing sent/bounced/replied counts
- **Run controls**: Trigger scrapers, funding scans, company intel refresh via UI
- **Excel exports** with conditional formatting (salary ranges, company quality)

### ✅ Application Tracking

- **Pipeline states**: shortlist → applied → interviewing → offer → rejected
- **Job notes**: Track version history and decision reasons
- **Analytics**: Conversion funnel, source quality, time-to-offer metrics

### ⏰ Scheduling

- **APScheduler** daemon: 9 AM + 4 PM IST by default (configurable)
- **Persistent runs**: Each run saves metadata (platform, count, errors, export paths)
- **Alerts**: SMTP email notifications for new jobs above salary/quality threshold

---

## Architecture

```
job_search/
├── api/                      # FastAPI server + dashboard SPA
│   └── server.py            # REST endpoints, WebSocket streams, static file serving
├── scrapers/                # Platform-specific scrapers (14 files)
│   ├── base.py              # Abstract BaseScraper
│   ├── linkedin.py, naukri.py, instahyre.py, ...
│   └── __init__.py          # SCRAPER_REGISTRY
├── services/                # Core business logic
│   ├── scoring.py           # Multi-factor job scoring + company normalization
│   ├── semantic_scorer.py   # Sentence-transformers embeddings
│   ├── company_intel.py     # Company profiles from MNC/VC registries + funded data
│   ├── connection_matcher.py# LinkedIn CSV import + warmth scoring
│   ├── dedup.py             # Cross-platform duplicate detection
│   ├── exporter.py          # CSV per-run + cumulative Excel
│   ├── notifier.py          # SMTP email alerts
│   ├── location_filter.py   # Delhi NCR validation
│   ├── outreach_writer.py   # Email template generation
│   └── cookie_manager.py    # Login credential storage
├── outreach/                # Outreach pipeline
│   ├── pipeline.py          # Main orchestration
│   ├── enricher.py          # Apollo + Prospeo contact enrichment
│   ├── db.py                # Separate SQLite (output/outreach.db)
│   ├── models.py            # OutreachContact, OutreachEmail schemas
│   ├── gmail_sender.py      # Gmail API integration
│   ├── templates.py         # Email templates (intro, follow-up, final)
│   └── reviewer.py          # Local HTTP review UI
├── vc_portals/              # VC fund registry + scraper
│   ├── registry.py          # 30 VCFund dataclasses with portal URLs
│   └── scraper.py
├── mnc_careers/             # MNC registry + scraper
│   ├── registry.py          # ~350 MNC dataclasses (listing URL, ATS override, HQ country)
│   ├── ats/                 # typed fetchers: workday, greenhouse, lever, smartrecruiters, successfactors(+unify), phenom, radancy, oracle_hcm, avature, amazon_jobs
│   ├── html_generic.py      # Playwright lane (JSON interception, cards, pagination, consent dismissal)
│   ├── filter.py            # postings → Jobs through the shared title/location filters
│   ├── discovery.py         # mnc-discover: probe, verify, emit entries; --repair for dead URLs
│   └── data/                # mnc_input.csv, discovery_overrides.csv
│   └── scraper.py
├── yc_startups/             # Y Combinator integration
│   ├── scraper.py           # Syncs YC batch directory
│   ├── enricher.py          # Founder data enrichment
│   ├── signals.py           # Job posting + recent updates detection
│   └── founder_scraper.py   # Scrapes founder LinkedIn profiles
├── funding/                 # Funding news scanner
│   ├── scanner.py           # TechCrunch, Inc42, YC batch sources
│   ├── models.py            # FundedCompany dataclass
│   └── exporter.py          # CSV + Excel export
├── storage/                 # Data layer
│   └── db.py                # JobDB with scoring, dedup, app tracking tables
├── models/                  # Pydantic schemas
│   ├── job.py               # Job model with score_reasons, priority_flags
│   └── __init__.py
├── config/                  # Configuration
│   ├── settings.py          # .env-based Pydantic settings
│   ├── search_params.py     # Title keywords, location, exp level, CTC bounds
│   └── scoring_rules.py     # Heuristic constants (title weights, keywords, thresholds)
├── browser/                 # Playwright management
│   └── context.py           # BrowserManager with stealth + cookie handling
├── scheduler/               # Job scheduling
│   └── runner.py            # APScheduler daemon with CronTrigger
├── data/                    # User inputs
│   └── candidate_profile.json  # Proof points for outreach writer
├── docs/                    # Protocols & learnings
│   ├── known_edge_cases.md  # Data quirks, API edge cases with file:line refs
│   ├── guidelines_and_learnings.md  # 18 codified patterns
│   └── protocol_to_identify_issues.md  # 7-phase audit protocol
├── static/                  # SPA assets
│   └── index.html           # Dashboard frontend
├── main.py                  # Typer CLI entrypoint (30+ commands)
├── requirements.txt         # Dependencies
└── CLAUDE.md / AGENTS.md    # Agent instructions
```

---

## Quick Start

### Prerequisites

- **Python 3.9+**
- **Playwright browsers**: `playwright install chromium`
- **`.env` file** with API keys + SMTP settings (see `.env.example`)
- **Optional**: `data/candidate_profile.json` for outreach drafting

### Installation

```bash
git clone <repo>
cd job_search
python -m venv .venv
source .venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env with your API keys, SMTP, Gmail OAuth paths, etc.
```

### First Run (30 seconds)

```bash
# Scrape jobs from all platforms
python main.py run

# Score and rank jobs
python main.py recommend

# View today's top jobs
python main.py today

# Start the dashboard
python main.py serve
# → Open http://localhost:8000
```

---

## CLI Commands (30+ Available)

### Job Scraping & Scheduling

```bash
# Run scrapers (one-off or filtered by platform)
python main.py run
python main.py run -p linkedin -p naukri

# Login to gated platforms (headed browser)
python main.py login instahyre
python main.py login linkedin

# Show scrape history
python main.py status

# Schedule recurring runs (9 AM, 4 PM IST)
python main.py schedule
```

### Supplementary Sources

```bash
# Scan funding news for recently funded companies
python main.py funding

# Scrape VC portal job listings
python main.py vc-jobs

# Scrape MNC careers portals (full run ≈ 15–40 min for ~350 companies)
python main.py mnc-jobs
python main.py mnc-jobs --only "SAP,Autodesk" --dry-run     # per-company table, nothing written
python main.py mnc-jobs --ats workday --cap 500

# Discover / verify careers portals for companies in mnc_careers/data/mnc_input.csv
python main.py mnc-discover --dry-run          # classification + candidates, no network
python main.py mnc-discover --browser          # probe + verify (Playwright for HTML-lane sites)
python main.py mnc-discover --repair --ats workday --apply   # re-verify existing entries, patch dead URLs

# All three above at once
python main.py run-all
```

### YC Startups

```bash
# Sync YC directory and detect hiring signals
python main.py yc-sync
python main.py yc-sync --batch S24,W25  # Specific batches

# Check which YC companies are actively hiring
python main.py yc-hiring-check

# Scrape & enrich founder LinkedIn data
python main.py yc-scrape-founders
python main.py yc-enrich-founders --all
```

### Decision Engine & Scoring

```bash
# Score all unscored jobs and show recommendations
python main.py recommend

# Top 50 jobs in "high" priority bucket
python main.py recommend --top 50 --bucket high

# Rescore all jobs (e.g. after config change)
python main.py recommend --rescore

# Today's best recommendations
python main.py today

# Refresh company profiles (MNC/VC status, funding data)
python main.py company-intel-refresh

# Import LinkedIn connection CSV for warmth scoring
python main.py connections-import path/to/linkedin_connections.csv
```

### Application Tracking

```bash
# Mark a job as shortlisted
python main.py shortlist --job-id JID123

# Update application status
python main.py apply-status --job-id JID123 --status applied
python main.py apply-status --job-id JID123 --status interviewing
python main.py apply-status --job-id JID123 --status rejected

# View pipeline funnel
python main.py pipeline-status
```

### Outreach & Recruitment

```bash
# Enrich contacts (Apollo search + enrichment)
python main.py outreach-enrich

# Review enriched contacts locally (http://localhost:8899)
python main.py outreach-review
# → Approve, edit, skip, or snooze each contact

# Send outreach emails (Gmail API)
python main.py outreach-send

# View outreach stats
python main.py outreach-status

# Reply to email thread
python main.py outreach-reply CONTACT_ID
```

### Drafting & Writing

```bash
# Generate outreach messages (requires candidate_profile.json)
python main.py draft-message --job-id JID123 --type recruiter
python main.py draft-message --job-id JID123 --type hiring-manager
python main.py draft-message --job-id JID123 --type warm-intro --mutual "Alice Smith"
```

### Analytics & Utilities

```bash
# Source quality + conversion funnel analysis
python main.py analytics

# Export jobs to CSV/Excel
python main.py export

# Web dashboard + REST API
python main.py serve
# → http://localhost:8000

# One-shot: scrape → dedup → score → export → notify
python main.py full-run

# Purge old jobs (safety: interactive confirmation)
python main.py purge-jobs --before "2025-12-01"
```

---

## Configuration

### Environment Variables (`.env`)

The authoritative list is `config/settings.py` (every field has a default; `.env` is loaded from the repo root regardless of CWD). Search titles/locations are **not** env vars — edit `config/search_params.py`.

```bash
# ── Email alerts (leave SMTP_HOST blank to disable) ──
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
ALERT_RECIPIENTS=

# ── Schedule ─────────────────────────────────────────
SCHEDULE_TIMES=09:00,16:00        # IST, comma-separated
POLL_INTERVAL_MINUTES=0
LOG_LEVEL=INFO

# ── Job aggregator APIs (free keys; scraper skipped while blank) ──
ADZUNA_APP_ID=                    # https://developer.adzuna.com/
ADZUNA_APP_KEY=
JOOBLE_API_KEY=                   # https://jooble.org/api/about
CAREERJET_AFFID=                  # https://www.careerjet.com/partners/api/

# ── MNC careers (defaults shown) ─────────────────────
MNC_MAX_POSTINGS=3000             # full-listing cap per company; keyword "net" beyond it
MNC_API_CONCURRENCY=12
MNC_HTML_CONCURRENCY=5
MNC_COMPANY_TIMEOUT=420

# ── Outreach: Apollo / Prospeo / Gmail OAuth ─────────
APOLLO_API_KEY=
APOLLO_RATE_LIMIT_PER_MINUTE=10
PROSPEO_API_KEY=
GMAIL_CREDENTIALS_PATH=credentials/gmail_credentials.json
GMAIL_TOKEN_PATH=credentials/gmail_token.json
OUTREACH_DAILY_LIMIT=25
OUTREACH_SENDER_NAME=Your Name
```

### Title & location filtering (`config/search_params.py`)

`title_keywords` / `titles` (accept phrases), `title_exclude_phrases`, `title_synonyms`, `title_token_fuzz_threshold` and `server_net_keywords` drive `services/title_filter.py`; NCR/remote tokens live in `services/location_filter.py`. After changing them run `python main.py purge-titles` to re-evaluate stored jobs.

### Candidate Profile (`data/candidate_profile.json`)

Required for outreach drafting:

```json
{
  "name": "Your Name",
  "current_role": "Product Manager @ Company",
  "experience_years": 6,
  "target_roles": ["Senior PM", "Principal PM"],
  "proof_points": [
    "Led product strategy for $5M+ revenue feature",
    "Managed cross-functional team of 8+",
    "Improved user retention by 35% via redesign"
  ],
  "linkedin_url": "https://linkedin.com/in/yourprofile"
}
```

---

## Database Schema

### Jobs DB (`output/jobs.db`)

- **jobs**: title, company, location, salary, platform, posted_date, apply_link, description, scraped_at, is_duplicate, **priority_score**, **priority_bucket**, score_reasons, priority_flags
- **company_profiles**: company_slug, is_mnc, is_funded, funding_series, vc_name, careers_page_present, scraped_at
- **applications**: job_id, status (shortlist/applied/interviewing/offer/rejected), notes, updated_at
- **network_contacts**: email, first_name, last_name, company, title, warmth_level (1°/2°/other)
- **job_connection_matches**: job_id, contact_id, warmth_score, mutual_connection_name
- **runs**: platform_list, job_count, duplicate_count, errors, timestamp

### Outreach DB (`output/outreach.db`)

- **outreach_contacts**: company, title, email, phone, linkedin_url, source (apollo/prospeo), verified_at, status (verified/failed), last_enriched_at
- **outreach_emails**: contact_id, template_type (intro/follow_up/final), recipient_email, subject, body_html, gmail_message_id, thread_id, status (sent/bounced/replied), sent_at, updated_at
- **outreach_credits**: source, total_credits, used_credits, reset_date, rate_limit_per_minute

---

## Scoring Deep Dive

### Relevance Score (0–100)

- Title keyword match (80 points max): checks `config/scoring_rules.py` PM keywords
- Location bonus: +5 if exact match, +2 if region
- Recency: -10 per week old (max -30)
- Direct source bonus: +10 if from VC/MNC/YC directly

### Salary Likelihood Score (0–100)

- **Explicit salary** in posting: +100
- **Company known for high pay**: +50 (from MNC/VC registries)
- **Funding series signal**: Seed+ (+30), Series A+ (+40), Series B+ (+50)
- **Experience level**: Senior/Principal roles (+20)

### Warmth Score (0–100)

- **0** until connections CSV imported
- **Direct connection** (+80)
- **1st degree** (+50)
- **2nd degree** (+20)
- **Mutual introduction available**: +10 bonus

### Company Quality Score (0–100)

- **MNC status**: +40
- **Funded status**: +20 (varies by series)
- **Multiple PM openings** at company: +15
- **Active careers page**: +10
- **VC affiliation**: +5

### Composite Priority Score

```
priority_score = (relevance × 0.45) + (salary × 0.30) + (warmth × 0.15) + (quality × 0.10)
```

**Buckets**:
- **High**: ≥ 75
- **Medium**: 50–74
- **Low**: < 50
- **Unscored**: `priority_bucket = ''` (no scoring attempted yet)

### Semantic Similarity (Latest)

Sentence-transformers generates embedding of candidate profile. Each job description compared for semantic distance. Added as 6th score dimension (experimental, not yet weighted into composite).

---

## Known Patterns & Pitfalls

> See `docs/guidelines_and_learnings.md` for full protocol.

1. **Company Slug Consistency**: Always use `_company_slug()` from `services/scoring.py`, never inline regex. Inconsistency causes profile lookups to miss.
2. **Unscored Sentinel**: `priority_bucket = ''` means never scored. Do NOT check `priority_score = 0` (a legitimately poor job scores 0).
3. **Funding Data Flow**: Funding scanner writes to `output/funded_companies_*.csv`. Company intel reads from CSV. Run `funding` before `company-intel-refresh` for current data.
4. **Location Defense-in-Depth**: Scrapers filter locally; pipeline re-validates. Catch misclassified (e.g., Naukri returning Mumbai in Delhi search).
5. **Resource Leaks**: Always `await page.close()` after `_get_page()`. Guard `page.goto()` in try/except.
6. **Two Databases**: Jobs in `output/jobs.db`, outreach in `output/outreach.db`. Never mix.
7. **Apollo Search ≠ Enrichment**: Search finds contacts but does NOT return emails. Always follow with Enrich.
8. **Selector Fragility**: Sites update CSS. Use fallback chains: `soup.select(".new") or soup.select(".old")`

---

## Testing & Smoke Tests

```bash
# Fastest: API-based scraper (no browser)
python main.py run -p remoteok

# Browser test (HTML parsing)
python main.py run -p naukri

# Full test (all 14 platforms)
python main.py run

# Scoring end-to-end
python main.py recommend --rescore

# Company intel
python main.py company-intel-refresh

# Outreach pipeline
python main.py outreach-status

# Import check
python -c "from scrapers import SCRAPER_REGISTRY; print(len(SCRAPER_REGISTRY))"
```

---

## Project Conventions

- **Absolute imports** from project root (e.g. `from models.job import Job`). Root is added to `sys.path` in `main.py`.
- **Type annotations**: `from __future__ import annotations` at top of all files for `X | Y` unions (Python 3.9 compat).
- **Logging**: Use structlog (`self._log` in scrapers, `structlog.get_logger(__name__)` elsewhere).
- **Error handling per-card**: Try/except inside scraper loops, log and continue. Never crash on one bad job.
- **HTML parsing**: BeautifulSoup for parsing, not regex. Playwright for SPAs.
- **Async/await**: All I/O is async (httpx for APIs, Playwright for browsers). Single-threaded (asyncio), safe to use `db.conn` directly.

---

## For Agents / Contributors

Before modifying code, read:

1. **`docs/known_edge_cases.md`** — data shapes, API quirks, runtime scenarios with file:line refs
2. **`docs/guidelines_and_learnings.md`** — 18 codified principles
3. **`docs/protocol_to_identify_issues.md`** — 7-phase audit protocol (use when debugging bugs)
4. **`CLAUDE.md` / `AGENTS.md`** — agent role instructions, file organizations, testing approach

After shipping a fix:
- Update `docs/known_edge_cases.md` with the new case
- Promote repeated patterns into `docs/guidelines_and_learnings.md`

---

## License

Private project. Built for PM job search targeting Delhi NCR, 5–7 years, 50+ LPA.

---

## Latest Changes (April 2026)

- ✨ Semantic similarity scoring added (sentence-transformers)
- 🎨 Centralized dashboard design system (single source of truth for colors)
- 🐛 Comprehensive logical bug fixes across scrapers, outreach, API, and services
- 📊 Dashboard v1 with job browser, outreach status, run controls
- 🏦 15+ VC portals added to registry

---

**Questions? See `CLAUDE.md` for agent instructions. Run `python main.py --help` for full command list.**
