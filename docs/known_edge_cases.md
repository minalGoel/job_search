# Known Edge Cases

> **Purpose:** Catalogue of data shapes, API quirks, and runtime scenarios that have broken naive implementations in this codebase. **Every item here is backed by a real bug that made it into `main`.** Consult this file when writing new scrapers, adding API endpoints, or touching the scoring/outreach pipeline.
>
> **When to update:** Any time a bug is rooted in "the data/API/library didn't behave the way we assumed," add it here with the file + line of the fix so future sessions can pattern-match.

---

## 1. Location strings are trickier than they look

| Input | Naive answer | Correct answer | Why |
|---|---|---|---|
| `""` / `None` | "missing" | **reject** | No way to verify it's NCR — refuse to ingest |
| `"Remote (US)"` | "remote ✓" | **reject** | Parenthesised country codes = regional restriction |
| `"Remote, EMEA"` | "remote ✓" | **reject** | EMEA is a non-India region |
| `"Remote, India"` | ambiguous | **accept** | India-wide remote counts |
| `"Remote - Bangalore"` | "remote ✓" | **reject** | Anchored to a non-NCR city |
| `"Hybrid - Gurugram"` | ambiguous | **accept** | Paired NCR city |
| `"Hybrid - Bangalore"` | "hybrid ✓" | **reject** | Paired with non-NCR city |
| `"Indianapolis"` | contains "india" → accept | **reject** | Use `\bindia\b` word-boundary regex |
| `"4-6 Yrs"` | valid location | **reject** | Naukri field-mapping bug — this is an experience string |
| `"Gurugram"` (Expedia) | trust it | **verify** | MNC scraper stamps this by fallback; doesn't mean the job is actually in Gurugram |

**Rule:** Use `services.location_filter.is_acceptable_location()` as the single source of truth. Never write inline location-allowlist checks.

**Canonical test set:** `services/location_filter.py` ships with 39 test cases covering every pattern above. When you add a new edge case, add it to the smoke test that runs from that module's docstring.

---

## 2. Search URL filters are cosmetic, not authoritative

Job portals accept `?location=`, `?country=`, `?region=` parameters but frequently **ignore them server-side** or use them only as sort hints. Confirmed offenders:

- **LinkedIn guest search** — `location=Delhi%2C+India` returns global results with Delhi-first ordering
- **Wellfound** — `?location=delhi` returns all roles
- **Expedia / Workday / Taleo / Greenhouse career portals** — `?location=India` returns global catalog
- **Most VC portfolio boards (Getro, Consider)** — no server-side location filter at all

**Rule:** Never trust a portal's URL-level filter. Extract `location` from **each individual result** and run it through `is_acceptable_location()` before appending to the jobs list. The pipeline-level gate in `main.py _run_all()` is a safety net, not the first line of defence.

**Corollary — MNC location fallback:** `_scrape_mnc()` previously fell back to `mnc.delhi_ncr_office` (e.g. "Gurugram") when no location element was found in the HTML. This compounded the URL-filter problem: Expedia's `?location=India` returned global results, the CSS selectors found no location tag, and the fallback branded every job as "Gurugram". 21 US/Europe roles entered the DB as Delhi NCR jobs. **Fix (April 2026):** the fallback was removed; an empty location stays empty and is rejected by `is_acceptable_location("")`. See `mnc_careers/scraper.py:130`.

---

## 3. Naukri's `placeholders` array is type-indexed, not positional

Naukri's API returns:
```json
"placeholders": [
  {"type": "experience", "label": "4-6 Yrs"},
  {"type": "salary",     "label": "..."},
  {"type": "location",   "label": "Delhi / NCR"}
]
```

Indexing by position (`placeholders[0]` for location) is **wrong** — the order varies per job. Always iterate and key by `ph["type"]`. See `scrapers/naukri.py:139`.

---

## 4. YCombinator cards: first-match-wins, not last-match-wins

YC job card text looks like: `"Full-time • Engineering • $100K • Remote • CA, US"`. The old code did:
```python
for part in parts:
    if loc_match(part):
        location = part   # BUG: overwrites; last match wins
```

A Remote-India-friendly card ending in `"CA, US"` would silently become a US job. **Always `break` after the first match**, or track "best match" explicitly. See `scrapers/ycombinator.py:145`.

---

## 5. `dedup_hash` must include a location component

If `dedup_hash` is computed from `(company, title)` only, a London "Senior Product Manager" at Expedia and a Delhi "Senior Product Manager" at Expedia collide and the second insert is marked as a duplicate. Use `services.location_filter.normalize_region(loc)` as the third component of the hash: it maps all NCR variants to `"delhi-ncr"`, all clean global remote to `"remote"`, and preserves individual city names for others. See `models/job.py dedup_hash`.

---

## 7. Hardcoded search queries silently ignore `SearchParams`

Every scraper **must** read the query from `self.search_params.title_keywords[0]`, not a literal `"product manager"` string. If a user changes `SearchParams.title_keywords = ["Product Lead"]`, hardcoded scrapers will silently continue scraping for "product manager" with zero indication. **Offender history:** `iimjobs.py` and `instahyre.py` both had this bug.

---

## 8. Unscored sentinel: `priority_bucket == ''`, not `priority_score == 0`

A job that genuinely has no positive signals can legitimately score **0** after scoring. If you treat `priority_score == 0` as "needs scoring," you'll rescore these jobs on every run and waste cycles. The real "never been scored" sentinel is `priority_bucket == ''` (empty string). Use:
```python
conditions.append("priority_bucket = ''")            # "unscored"
conditions.append("priority_bucket NOT IN ('low','')")  # "worth showing"
```

---

## 9. Application tracker has **three** lurking bugs if you're not careful

1. **Status vocabulary drift** — the CLI and the API used different status enum sets (`interviewing` vs `interview`, `reached_out` vs `screening`, etc.). Fix: `storage/db.py APPLICATION_STATUSES` is the single canonical frozenset; import from there.
2. **`applied_at` gets wiped** — if an upsert with `applied_at=None` runs after a successful application insert, a naive `SET applied_at = excluded.applied_at` erases the original timestamp. Fix: `COALESCE(excluded.applied_at, applications.applied_at)` in the upsert.
3. **Two app-ID schemes** — CLI used `hash("app|" + job_id)` and API used `f"app_{job_id}"`, creating two rows for the same job. Fix: `storage/db.application_id_for(job_id)` is the single source of truth.

---

## 10. `/api/jobs` application join is nondeterministic with duplicate rows

Even after unifying the ID strategy, historical databases still have duplicate application rows per job. Joining with `{job_id: row}` overwrites in SELECT order — final status depends on whatever SQLite returned last. Always `ORDER BY COALESCE(last_action_at, '') DESC` and take the first row per `job_id`.

---

## 11. MNC careers scraper: do **not** fall back to `mnc.delhi_ncr_office`

Historical bug: when the HTML job card lacked a `.location` element, the scraper silently defaulted to `mnc.delhi_ncr_office`. Every Expedia PM role on the global careers page ended up stamped as "Gurugram". **Rule:** on extraction failure, set `location = ""` → `is_acceptable_location()` → `continue`. Never stamp a default location.

---

## 12. Resource leaks on exception paths

Playwright pages and SQLite connections are two places where naive try/except without `finally` causes real production pain.

- **Every `page = await context.new_page()` needs a `try/finally` with a `page=None` sentinel** so exceptions in `wait_for_selector`, parsing, or `page.content()` still close the page. Offender history: linkedin, indeed, naukri, wellfound all had this leak.
- **Every `db = _jobs_db()` in an API endpoint needs `try/finally: db.close()`**. `raise HTTPException` before `db.close()` silently leaks the connection. Offender history: `/api/jobs/{job_id}`, `/api/jobs/{job_id}/shortlist`, `/api/jobs/{job_id}/status`.
- **`_get_page()` helpers must close the page if `page.goto()` fails**, then re-raise. Otherwise a network timeout accumulates pages across retries.

---

## 13. Apollo rate limiter has two footguns

- **`rate_limit = 0`** (the "disabled" config) crashes the old `request_count % rate_limit == 0` with `ZeroDivisionError`
- **"Sleep 60s every Nth call"** allows N calls to burst back-to-back, then pauses — it doesn't prevent instantaneous rate violations

Use a **token-bucket / min-delay** pattern: track `_last_call_ts` and sleep `(60.0/rate_limit) - elapsed` on every call. See `outreach/apollo_client.py _rate_limit()`.

---

## 14. Legal suffixes break company matching

`"Acme Technologies Pvt Ltd"` and `"Acme Inc."` are the same company for every practical purpose, but a naive `LOWER(company) = LOWER(?)` comparison treats them as different. The scorer's `_company_slug()` strips legal suffixes (pvt, ltd, inc, corp, technologies, solutions, pte, plc, gmbh, bv, ...) and produces the bare `"acme"` slug. **Any module that dedups or matches companies must use `_company_slug()`** — never inline regex, never raw lowercasing. Offender history: `outreach/db.company_has_outreach()`.

---

## 15. `playwright-stealth` API churn

The library has renamed its apply method at least twice:
- v1.x: module-level `from playwright_stealth import stealth_async; await stealth_async(context)`
- v2.x: `Stealth().apply_stealth(context)` (sometimes sync-returning)
- v2+: `Stealth().apply_stealth_async(context)` (coroutine-returning)

Use a defensive shim that tries multiple method names and handles both sync/async returns. See `browser/context.py get_context()`.

---

## 16. `_safe_scrape` must propagate error info, not swallow it

Returning `[]` on exception loses the reason for failure — `runs.errors` ends up empty and every platform looks like "0 results" instead of "TimeoutError: selector timeout". Return a tuple `(jobs, error_message)` so the orchestrator can record real failures in the `runs` table.

---

## 17. Direct-source scoring bonus misses dynamic platform names

`DIRECT_SOURCE_PLATFORMS` is a `frozenset` of exact names, but the VC/MNC scrapers emit dynamic names like `vc_accel_india`, `mnc_expedia_group`. Exact-match check misses them entirely. Use:
```python
is_direct = (
    platform in DIRECT_SOURCE_PLATFORMS
    or platform.startswith("vc_")
    or platform.startswith("mnc_")
)
```

---

## 19. RemoteOK has two URL fields — `url` vs `apply_url`

RemoteOK's JSON API returns two distinct URL fields per job item:

| Field | Value | Purpose |
|-------|-------|---------|
| `url` | `"https://remoteok.com/remote-jobs/1130997"` | The RemoteOK canonical listing page |
| `apply_url` | `"https://jobs.ashby.io/..."` | The employer's direct ATS application link |

Using `item.get("url")` as the apply destination sends candidates back to the RemoteOK listing they came from, not the application form. Every observed API item has `apply_url` as a full absolute URL.

**Fix:** `apply_url = item.get("apply_url", "") or item.get("url", "")` — prefer the employer ATS link, fall back to the listing page only when `apply_url` is absent. See `scrapers/remoteok.py`.

---

## 18. Documentation–code drift

`CLAUDE.md` stated that `_company_slug()` "strips punctuation and legal suffixes" but the actual implementation only stripped punctuation. The docs were right; the code was wrong for months. **When auditing, always cross-check docs against the implementation** — either can be the bug.

---

## 20. Indian name classifier: three pitfalls that cause silent mis-classification

The offline ML classifier (`yc_startups/name_classifier.py`, `build_training_data.py`) has several non-obvious failure modes:

| Pitfall | Symptom | Fix |
|---|---|---|
| **Random downsampling drops known names** | "Arjun Mehta" → not Indian (f=0.580) — "arjun" was randomly excluded when 3,724 Indian first names were downsampled to 918 | `build_training_data()` now keeps ALL 556 hand-curated `INDIAN_FIRST_NAMES` guaranteed; only `CSV_INDIAN_FIRST_NAMES` is randomly sampled to fill remaining 2:1 budget |
| **`AMBIGUOUS_EXCLUSIONS` removes non-Indian training signal** | "Carlos Garcia" classified as Indian (l=0.823) — "garcia" was in `AMBIGUOUS_EXCLUSIONS`, removing it from BOTH training sets; model never learned it as non-Indian | Spanish/Latin surnames removed from `AMBIGUOUS_EXCLUSIONS`; non-ambiguous for Indian classification and must stay in the non-Indian training set |
| **Hyphenated first names produce spurious n-grams** | "Jan-Hendrik Ruettinger" → classified as Indian — "jan-hendrik" feeds n-grams like "ndr", "dri" (from "hendrik") that resemble Indian names | `classify()` and `classify_batch()` split on `-` and use only the pre-hyphen token for the first-name model |
| **n-gram range too narrow misses short distinctive names** | "gupta", "mehta" scored below threshold — with `ngram_range=(2,4)`, a 5-char name never appears as a complete n-gram feature | Changed to `ngram_range=(2,5)` + `min_df=1` |

**Threshold:** `THRESHOLD_SINGLE=0.88` (not 0.80) eliminates Hebrew "sha-" false positives (Shahar l=0.856) and Spanish surname false positives (Garcia l=0.875) while retaining all standard Indian names via the `THRESHOLD_BOTH=0.65` dual-threshold path.

**Training data:** curated first names (`INDIAN_FIRST_NAMES`) and CSV supplement (`CSV_INDIAN_FIRST_NAMES`) are kept in separate sets so priority-based balancing always includes curated names. Last names: `HIGH_QUALITY_LAST_NAMES` (545 entries from `last names.csv`) supplements via set union.

## 21. `requires_login` was decorative — scrapers ran without cookies and "failed"

`BaseScraper.requires_login` was set on four scrapers but never read anywhere; `api/server.py` kept its own hardcoded `LOGIN_REQUIRED` set. A login-gated scraper with no `cookies/<name>.json` launched Chromium, hit an auth wall and was recorded as an *error*.

**Fix (Sept 2026):** `services/preflight.py` — `partition()` decides before instantiation. Skips are recorded in `runs.errors` with the `"skipped: "` prefix (no schema change); `status`, `/api/runs` and the dashboard split them from real errors via `split_run_notes()`. A scraper that discovers mid-run that it cannot proceed (401/403 on an API key) raises `ScraperSkipped`, which `_safe_scrape` reports as `"skipped: …"` without a traceback. `_run_all` launches Chromium only when a runnable scraper has `uses_browser=True`.

## 22. Title filter: substring matching accepted "Production Manager"; whole-phrase fuzzy is unsafe

`"product" in t and "manager" in t` accepted "Production Manager" and "Product Marketing Manager". Replacing it with `rapidfuzz.fuzz.token_set_ratio("product manager", …)` looked tempting but scores "production manager" at 90.9 — above any sane threshold. Per-token `fuzz.ratio` separates cleanly (prodcut 85.7 / manger 92.3 pass; production 82.4 / project 71.4 / management 70.6 fail).

**Rule (services/title_filter.py):** exact contiguous accept phrase → accept; exclude phrase → reject; per-token fuzzy ≥ 85 → accept. Exact runs *before* exclusions so "Product Manager – Production Tools" stays accepted. All phrases come from `config/search_params.py`; `main.py` calls `configure(params)` once. `purge-titles` evaluates the same function in Python — never a SQL `LIKE` copy of the rule.

## 23. Aggregator APIs: HTML in titles, per-request redirect params, odd timestamps

- **Adzuna** wraps matched words in `<strong>` inside `title`/`description` → `strip_html()` before use. `redirect_url` carries per-request `se=`/`v=` tokens and *needs* them to resolve, so the stored `apply_link` keeps the raw URL while `Job.id` is computed over `stable_link()` (scheme+host+path) via `stable_job_id()` — otherwise every run creates new ids for the same ad.
- **Jooble** emits 7-digit fractional seconds (`2026-09-15T00:00:00.0000000`) which `datetime.fromisoformat` rejects → `parse_iso_date()` trims to 6 digits. Its `link` also carries session params.
- **Careerjet** requires `affid`, `user_ip`, `user_agent` *and* `url` on every call; a missing one returns `type: "ERROR"`. `type: "LOCATIONS"` means the location string was ambiguous — skip that variant, don't fail.
- All three: pagination advances by `len(returned)` and stops on an empty page — servers clamp page sizes.

## 24. `.env` and `cookies/` were resolved relative to CWD

`Settings.model_config.env_file=".env"` and `Path("cookies")` in seven scrapers/modules meant running from any directory but the repo root silently used defaults and found no cookies. Both are now absolute (`BASE_DIR/.env`, `self.cookies_dir = settings.COOKIES_DIR`).

## 25. `BrowserManager.get_context` check-then-create race

`get_context()` checked `self._contexts` and then awaited `new_context()` before storing the result. Concurrent callers for the same platform (the MNC HTML lane runs 5 companies at once under one `"mnc_careers"` context) each created a context; only the last was cached and closed on `stop()`. Creation now happens under a per-instance `asyncio.Lock` with a re-check inside.

## 26. Workday CXS: `limit` is capped at 20, `total` is only reported on the first page, tenants migrate hosts

- `POST /wday/cxs/{tenant}/{site}/jobs` returns at most 20 postings per call; pagination must advance by `offset`. `total` is correct at `offset=0` and **0 on every later page** — `paginate()` trusts the first page's total.
- `locationsText` for multi-site postings is literally `"3 Locations"`; the real cities are only in the job-detail endpoint (`GET /wday/cxs/{tenant}/{site}{externalPath}` → `jobPostingInfo.location`, `additionalLocations`). We resolve it only for postings whose title passes the filter.
- 42 of 51 registry Workday URLs were dead (HTTP 422/404/500): tenants had moved data centre (`genpact.wd5` → `wd108`) or renamed the site (`Philips_External_Careers` → `jobs-and-careers`). The old generic HTML scraper hid this as "0 results". `mnc-discover --repair` sweeps host × site variants and patches the registry; the per-company `source_runs` table now makes such rot visible.

## 27. Eightfold's public API refuses non-browser callers

`GET https://{tenant}.eightfold.ai/api/apply/v2/jobs` answers `403 {"message": "Not authorized for PCSX"}` unless the request comes from the site's own browser session. Detected `eightfold` sites (incl. custom domains like `careers.haleon.com`, `careers.qualcomm.com`) therefore run in the Playwright HTML lane, whose JSON interception captures the very same API response. `api_type="eightfold_api"` exists for tenants whose API happens to be open.

## 28. SuccessFactors comes in two flavours; some tenants sit behind Akamai

- **Classic** (`jobs.sap.com`, `careers.swissre.com`, …): `GET {base}/search/?q=&startrow=N` returns server-rendered `a.jobTitle-link` rows, 25 per page, total in `span.paginationLabel` — the typed fetcher handles these.
- **Career Site Builder "Unify"** (`jobs.bt.com`, `jobs.worldline.com`, `jobs.tuvsud.com`, `jobs.danfoss.com`, `careers.hcltech.com`, `jobs.grundfos.com`, `jobs.pirelli.com`): the same URLs return a `jobResultsCard` config and **no rows** — results are fetched by the page's own JS after a search, and even the browser lane sees nothing on `/viewalljobs/`. These are registered as `api_type="html"` and currently yield `empty`; a dedicated fetcher is parked.
- **Akamai-fronted** tenants (`careers.goindigo.in`, `careers.radissonhotels.com`, `careers.loreal.com`, `jobs.systra.com`, `careers.cevalogistics.com`, `careers.hellmann.com`) answer 403 to httpx → `api_type="html"`.

## 29. Registry `?q=` URLs are nets, not filters; slug-guessed boards collide

- Historical `pm_search_url` values carried `?q=product+manager`. Portal search is a volume hint (guidelines §12): the primary fetch strips it (`strip_search_params`) and pulls the full listing; the searched URL is reused only as a supplementary net when a portal exceeds `MNC_MAX_POSTINGS`.
- Guessing an ATS board from a company slug is dangerous: `api.smartrecruiters.com/v1/companies/knight` is "Knight Gayles" (not Knight Frank) and `boards.greenhouse.io/indigo` is an insurer (not IndiGo). Discovery therefore never uses first-token slugs, checks the board's own company name, and rejects slug-probe boards with fewer than 10 postings.
- Two CSV "fuzzy matches" were different companies: Fidelity International ≠ Fidelity Investments (token_set_ratio 100!), Publicis Groupe ≠ Publicis Sapient. `CSV_ALIASES` in `mnc_careers/discovery.py` is the only source of alias truth; fuzzy similarity is reported, never acted on.

## 30. Phenom People sites: the listing lives behind `POST /widgets`, and the URL shape is only a hint

Phenom career sites (`/{country}/{lang}/search-results`, e.g. `careers.adobe.com/us/en/search-results`, `careers.dhl.com/global/en/search-results`) render 10 jobs from an inline `phApp.ddo` blob and load the rest via `POST https://{host}/widgets` with `ddoKey="refineSearch"`. The endpoint honours `size` (100 works), `from` (offset), `keywords` (our cap-hit net) and reports `totalHits`; `lang` comes from `"locale"` in the page HTML, `country` from the path. The `applyUrl` is the external apply link (Avature etc.) — fine as `apply_link`; `jobSeqNo` is the stable id.

The `/search-results` URL shape is shared with other vendors (JPMorgan, Fidelity, Zendesk). The fetcher therefore checks the page for `phApp` and raises `NotThisATS`, which the orchestrator turns into a reroute to the HTML lane (the one deliberate exception to "no automatic lane reroute"). `_run_mnc_jobs` starts the browser whenever a Phenom-detected entry has no explicit `api_type`, so the reroute always has somewhere to go.

## 31. Title gate is "anything with product"; sorting happens via categories (user decision, Sept 2026)

The gate (`SearchParams.title_keywords = ["product"]`, no exclusions) deliberately lets Product Marketing / Owner / Design / Analyst titles through. `services.title_filter.categorize()` buckets them (`product_manager`, `product_leadership`, `product_owner`, `product_marketing`, `product_design`, `product_analyst_ops`, `product_engineering`, `other_product`) for the dashboard filter, and `config/scoring_rules.TITLE_WEIGHTS` demotes the non-PM families so PM/leadership roles still rank first. Because the gate is a single token, `title_filter` evaluates **multi-word accept phrases → exclusions → single-token accept → fuzzy** — otherwise a configured exclusion could never fire. "Production Manager" still fails (fuzz 82 < 85). To go back to the strict gate: `title_keywords=["product manager"]`, `title_exclude_phrases=["production", "product marketing"]`.

## 32. Location rule: "mentions Gurgaon/NCR (any spelling) or remote → in; only other locations → out"; remote/hybrid preferred

Multi-location strings that include an NCR city (`"Bengaluru; Gurgaon"`, `"Pune / Gurgaon"`) are accepted; strings that only name other cities/countries are rejected. `NCR_TOKENS` now includes Gurgaon misspellings/abbreviations (`gurgoan`, `gurugaon`, `ggn`) and localities (`cyber city`, `udyog vihar`, `manesar`, `greater noida`). `work_mode()` derives remote/hybrid/onsite/unknown from location (then title, then the description head); `WORK_MODE_BONUS` gives remote +12 / hybrid +10 relevance and the dashboard filters on it. `"Remote, US"` / `"Remote - Estonia"` are rejected by the country-token check (§ above) — "remote" only counts when no other country is named.

## 33. Radancy / Oracle HCM / Avature / SuccessFactors "Unify" — the other four ATS APIs

| ATS | How the listing is actually served | Gotcha |
|---|---|---|
| Radancy (TalentBrew, `/search-jobs`) | `GET {prefix}/search-jobs/results?…CurrentPage=N&RecordsPerPage=50` + `X-Requested-With` → JSON with an HTML fragment in `results` and `data-total-results` | The **full** parameter set is required (a trimmed request returns an empty fragment). Two skins: `<a><h2>…<span class="job-location">` and `li.sr-job-item h3 a` with `span.sr-job-location`; "Multiple Locations" → take the city from the `/job/{city}/…` path. Dell/NetApp/Pearson/Mott MacDonald/3ds/McKinsey all *look* like Radancy by URL and aren't (Akamai 403, SuccessFactors classic, DirectEmployers `.jobs` microsite, dead path, custom) — see §34. `jobs.ikea.com` *is* Radancy but each 50-row page is a 1.7 MB fragment that takes 11–50 s server-side, so it exhausts `MNC_HTTP_TIMEOUT` (25 s) and the 420 s company budget — a known `failed` row, not a parser bug. |
| Oracle Recruiting Cloud | `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber={site},limit=100,offset=N` → `items[0].TotalJobsCount`, `requisitionList[]` | Many custom domains front it (`jobs.akamai.com`, `careers.americanexpress.com`); the site id is in the `/hcmUI/CandidateExperience/en/sites/{site}` path. `WorkplaceType` carries Remote/Hybrid. |
| Avature (`/SearchJobs`) | server-rendered `article.article--result`, 12 per page via `?jobOffset=N`, keyword net via `/SearchJobs/{keyword}` | total is only in page text ("N results"). |
| SuccessFactors "Unify" | `POST /services/recruiting/v1/jobs` `{keywords, locale, location, pageNumber, sortBy:"recent"}` → `jobSearchResult[].response`, `totalJobs`, 10 per page | `locale` must match the tenant (`currentLocale` in the page — Danfoss returns 0 for `en_US`, needs `en_GB`). Job URL is `/job/{Title}/{id}-{locale}`. The classic-vs-Unify decision is made from the first `/search/` page (`jobTitle-link` rows vs `jobResultsCard`). |

`phenom`, `radancy` and `avature` are detected from URL shape only. Each typed fetcher raises `NotThisATS` when the *first unfiltered page* fails (Radancy: any `FetchError` or non-string `results`; Avature: any `FetchError`, or no `article--result` and no "avature" in the page; Phenom: `/widgets` not JSON) and `mnc_careers/scraper.py` reroutes that company to the HTML lane in the same run. `_run_mnc_jobs` therefore starts the browser whenever such an entry has no explicit `api_type`. Run 3 → run 4: this turned 7 Radancy + 1 Avature `failed` rows into `ok`/`empty` HTML-lane rows.

## 34. Registry repair pitfalls (Sept 2026): same URL in two fields, absorbed companies, look-alike company ids

- **`apply_repairs` must anchor on `pm_search_url=`** — discovered entries carry the identical URL in `careers_url` and `pm_search_url`, and a plain `src.index(old_url)` patched `careers_url` and left the dead listing URL in place (Mace, MSC). `mnc_careers/discovery.py::apply_repairs` now looks for the keyword form first and only falls back to the first occurrence for positional (legacy) entries.
- **Acquired companies keep a working-looking tenant.** `ansys.wd1.myworkdayjobs.com/Ansys` answers 200 with an empty shell (Ansys → Synopsys, 2025); `juniper.wd5` is retired and `careers.juniper.net` → `careers.hpe.com/juniper` (Juniper → HPE, 2025). Such entries are kept in the registry with `pm_search_url=""` and an `ABSORBED …` note so they are not targets (`select_targets` needs a listing URL) but still resolve CSV/alias lookups; the parent entry lists their roles.
- **SmartRecruiters returns `200 {"totalFound":0}` for a company id that does not exist**, so a slug guess can never be told apart from an empty tenant — and a *different* company can own a look-alike id (`MSC1` is Medical Science & Computing, not Mediterranean Shipping). Only trust an id that appears in the company's own page or that returns postings whose `company.name` matches.
- **URL-shape look-alikes**: `jobs.netapp.com/search-jobs/…` is SuccessFactors classic (`/search/`), `pearson.jobs` is a DirectEmployers microsite whose real ATS is Oracle HCM (`hccz.fa.em3.oraclecloud.com`, site `CX_2`), `jobs.cisco.com/jobs/SearchJobs` (Avature-shaped) now redirects to the Phenom site `careers.cisco.com/global/en`. `mnc-discover --repair` with an override row fixes these; never hand-edit a URL without letting the real fetcher verify it.
- `careers.hyatt.com/…/SearchJobs` is an Avature shell that is a 4.6 KB JS stub to httpx → `api_type="html"` (browser lane parses ~40 cards/page).

## 35. Tracker: an unknown application status silently lands in "Saved"

`loadTracker()` bucketed any status without a kanban column into `shortlisted`, so roles the user
**skipped** (a real `APPLICATION_STATUSES` value written by the All Jobs "Skip" button) kept showing
as saved. Every status the API can write needs a column (Skipped is collapsed behind a topbar toggle)
— the fallback is only for corrupt data. Kanban cards were drag-only with no detail view; they now
open a modal fed by `GET /api/jobs/{id}` (decorated with `title_category`/`work_mode` like the list).
Regression tests: `tests/test_api_server.py`. Found by `/qa`, 2026-09-21.
