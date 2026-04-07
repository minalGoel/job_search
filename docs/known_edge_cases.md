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

## 5. WeWorkRemotely region is a dedicated XML element, not description text

WWR RSS items expose region restriction via a **dedicated `<region>` child element** on `<item>` (e.g., `<region>USA only</region>`, `<region>Anywhere in the World</region>`). The `<description>` CDATA body contains **no** `"Region:"` text substring.

An older implementation used `re.compile(r"region\s*:?\s*([^<\n.]+)", re.IGNORECASE)` against the description body — this regex **never matches** the current feed format, so `raw_region` is always `""` and every job is stored as `location = "Remote"`, causing US-only and EU-only jobs to pass `is_acceptable_location()` and enter the database.

**Fix (confirmed April 2026):** Read the element directly — `raw_region = item.findtext("region") or ""`  — then synthesise `"Remote — {raw_region}"` so `is_acceptable_location()` can reject restricted regions. See `scrapers/weworkremotely.py`.

---

## 6. `dedup_hash` must include a location component

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
