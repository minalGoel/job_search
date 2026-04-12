# Job Search Aggregator

An async Python CLI for aggregating Senior Product Manager roles from job boards, VC portfolio pages, MNC career sites, YC companies, and funding news. The tool deduplicates listings, scores and ranks jobs, tracks applications, and supports an outreach workflow for shortlisted roles.

Designed for a PM job seeker targeting Delhi NCR, 5-7 years of experience, 40+ LPA, and Tech/SaaS/B2B roles.

## What It Does

- Scrapes 14 job platforms, including API-based sources like RemoteOK and RSS-based sources like We Work Remotely
- Scans VC job portals and MNC career pages for Delhi NCR-relevant PM roles
- Tracks recently funded companies and YC hiring signals
- Scores jobs with heuristic, company-quality, warmth, and semantic signals
- Imports LinkedIn connections to improve warmth scoring
- Generates outreach drafts, reviews them locally, and sends via Gmail API
- Schedules recurring runs and exports per-run CSV plus cumulative Excel reports

## Quick Start

### Prerequisites

- Python 3.9+
- Playwright browser drivers: `playwright install chromium`
- A populated `.env` file for SMTP, Apollo, Gmail, Prospeo, and scheduling settings

### Install

```bash
git clone <repo>
cd job_search
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

### First Run

```bash
python main.py run
python main.py recommend
python main.py today
```

## Common Commands

### Job Scraping

```bash
python main.py run
python main.py run -p naukri -p linkedin -p indeed
python main.py login instahyre
python main.py status
python main.py schedule
```

### Supplementary Sources

```bash
python main.py funding
python main.py vc-jobs
python main.py mnc-jobs
python main.py run-all
```

### YC Workflow

```bash
python main.py yc-sync
python main.py yc-sync --batch S24,W25
python main.py yc-hiring-check
python main.py yc-enrich-founders --all
```

### Decision Engine

```bash
python main.py recommend
python main.py recommend --top 50 --bucket high
python main.py recommend --rescore
python main.py today
python main.py company-intel-refresh
python main.py connections-import linkedin.csv
```

### Application Tracking

```bash
python main.py shortlist --job-id JOBID
python main.py apply-status --job-id JOBID --status applied
python main.py pipeline-status
```

### Outreach

```bash
python main.py draft-message --job-id JOBID --type recruiter
python main.py draft-message --job-id JOBID --type hiring-manager
python main.py draft-message --job-id JOBID --type warm-intro --mutual "Alice Smith"
python main.py outreach-enrich
python main.py outreach-review
python main.py outreach-send
python main.py outreach-status
python main.py outreach-reply CONTACT_ID
```

## Repository Layout

```text
job_search/
├── scrapers/       # Platform-specific scrapers
├── services/       # Scoring, dedup, exporter, notifier, matching
├── outreach/       # Apollo/Gmail outreach pipeline
├── funding/        # Funding news scanner and export helpers
├── vc_portals/     # VC portal registry + scraper
├── mnc_careers/    # MNC registry + scraper
├── yc_startups/    # YC directory sync, hiring signals, enrichment
├── storage/        # SQLite access layer
├── scheduler/      # APScheduler runner
├── browser/        # Playwright context management
├── config/         # Settings and search parameters
├── models/         # Shared Pydantic models
├── data/           # Candidate profile inputs
├── docs/           # Protocols, edge cases, and learnings
├── main.py         # Typer CLI entrypoint
└── requirements.txt
```

## Configuration

Key environment values live in `.env`:

- SMTP settings for alerts
- `APOLLO_API_KEY` for contact enrichment
- `PROSPEO_API_KEY` as the fallback email finder
- Gmail OAuth paths for outreach sending
- Search title, location, experience, and salary bounds
- Scheduler timing and log level

The outreach writer also expects `data/candidate_profile.json` to be filled in with your proof points before it can produce useful drafts.

## Working Notes

- Read `docs/known_edge_cases.md`, `docs/guidelines_and_learnings.md`, and `docs/protocol_to_identify_issues.md` before changing scrapers, scoring, outreach, or API code
- `AGENTS.md` and `CLAUDE.md` contain the repo-specific agent instructions
- `priority_bucket = ''` is the unscored sentinel
- All company matching should use `services/scoring._company_slug()`
- The funding scanner writes to `output/funded_companies_*.csv`, which is then read by company intelligence refresh

