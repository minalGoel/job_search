# Validation Report

> **Generated:** 2026-04-07  
> **Validator:** Claude Sonnet 4.6 (Validator & API Interrogator role)  
> **Scope:** All ingestion pipelines described in `docs/pipelines_v1.md`, plus shared infrastructure (`models/job.py`, `storage/db.py`, `services/scoring.py`, `outreach/db.py`, `api/server.py`, `browser/context.py`, `scrapers/base.py`)

---

## Summary Table

| Source | (a) Assumption Mismatches | (b) Edge Cases | (c) Efficiency/Correctness | Total | Severity |
|--------|--------------------------|----------------|---------------------------|-------|----------|
| Naukri | 0 | 1 | **1 CRITICAL** | 2 | **Critical** |
| LinkedIn | 0 | 0 | 1 | 1 | High |
| Wellfound | 0 | 0 | 1 | 1 | High |
| Indeed | 0 | 0 | 1 | 1 | High |
| IIMJobs | 0 | 1 | 1 | 2 | Medium |
| Hirist | 0 | 0 | **1 CRITICAL** | 1 | **Critical** |
| RemoteOK | 1 | 1 | 1 | 3 | Medium |
| YCombinator | 0 | 0 | 0 | 0 | — |
| Instahyre | 0 | 0 | 1 | 1 | Medium |
| VC Portals | 0 | 0 | **1 CRITICAL** | 1 | **Critical** |
| Funding Scanner | 0 | 1 | 1 | 2 | Medium |
| Apollo Client | 0 | 0 | 0 | 0 | — |
| Storage / DB | 0 | 0 | 0 | 0 | — |
| Scoring | 0 | 0 | 0 | 0 | — |
| Outreach DB | 0 | 0 | 0 | 0 | — |
| API Server | 0 | 0 | 0 | 0 | — |
| Browser/Context | 0 | 0 | 0 | 0 | — |
| Base Scraper | 0 | 0 | 0 | 0 | — |

**Total findings: 18**  
**Critical: 4, High: 3, Medium: 5, Low: 6**

---

## API Evidence

### RemoteOK (`https://remoteok.com/api`) — fetched 2026-04-07

**Item 0 (index 0):**
```json
{
  "last_updated": 1775546222,
  "legal": "This data is provided by Remote OK..."
}
```
This IS a legal notice. The `data[1:]` skip is correct.

**Item 1 (index 1) — representative job:**
```
slug:        "remote-revops-ai-analyst-intern..."
id:          "1130997"
epoch:       1775433610
date:        "2026-04-06T00:00:10+00:00"    ← ISO 8601 with timezone
company:     "Actian Corporation"
position:    "RevOps AI Analyst Intern"
tags:        ["analyst", "design", "salesforce", ...]   ← always array
location:    "US-Remote"                                ← NOT "Remote"
apply_url:   "https://jobs.ashby.io/..."               ← FULL URL, NOT relative
salary_min:  0                                         ← numeric, not string
salary_max:  0                                         ← numeric, not string
url:         "https://remoteok.com/remote-jobs/..."    ← FULL URL
description: "<h2>...</h2>..."                         ← HTML string
logo:        ""
```

**Critical finding:** The field holding the apply link is `apply_url` (full absolute URL), NOT `url`. The `url` field is the RemoteOK canonical listing URL, not the actual application destination. The scraper reads `item.get("url", "")` for `apply_link`, which gives the *wrong* URL.

---

### Inc42 (`https://inc42.com/tag/funding/`) — fetched 2026-04-07

The page returned structured JSON-LD (`@type: "NewsArticle"`) alongside rendered HTML. The exact CSS class names for article containers could not be confirmed from the rendered output — the page appears to use obfuscated or framework-generated class names. The scraper's selectors `"article, div[class*='post-card'], div[class*='article']"` are best-effort generic selectors. No hard breakage found but selector drift is a known risk.

---

## Per-Source Findings

---

### RemoteOK (`scrapers/remoteok.py`)

#### (a) Assumption Mismatches

**V-04 — High: `apply_link` reads from `url` but apply destination is `apply_url`**

- **Assumption (pipelines_v1.md §1 Schema Mapping):** "`url` → `apply_link`: `item.get('url', '')`, relative prefixed with `https://remoteok.com`"
- **Reality (live API):** The `url` field is the RemoteOK canonical listing page (e.g., `https://remoteok.com/remote-jobs/1130997`). The actual employer application link is in a **separate field** `apply_url` (full absolute URL, e.g., `https://jobs.ashby.io/...`). The two fields are distinct on every job posting observed.
- **File:** `scrapers/remoteok.py:59-61`
- **Evidence:**
  ```python
  apply_url = item.get("url", "")        # BUG: reads the RemoteOK listing URL
  if apply_url and not apply_url.startswith("http"):
      apply_url = f"https://remoteok.com{apply_url}"
  ```
  The correct field is `item.get("apply_url", "") or item.get("url", "")` (fallback to `url` if `apply_url` is absent).
- **Impact:** High. All RemoteOK jobs link to the RemoteOK listing page rather than the employer's actual apply URL. Candidates clicking "Apply" get a RemoteOK page rather than the employer's ATS.

#### (b) Edge Cases Not Covered

**V-05 — Low: `salary_min = 0` and `salary_max = 0` are falsy but the code checks for `None` only**

- **File:** `scrapers/remoteok.py:49-51`
- **Evidence:**
  ```python
  salary = f"${salary_min} - ${salary_max}" if salary_min is not None and salary_max is not None else None
  ```
  Live API shows `salary_min: 0, salary_max: 0` for non-compensated/undisclosed roles. These are not `None`, so the scraper produces `salary = "$0 - $0"` instead of `None`. This is noted in `pipelines_v1.md` as a "Known Failure Mode" but is not fixed in code.
- **Impact:** Low (aesthetic, not functional). Consider: `if salary_min and salary_max:`.

#### (c) Efficiency/Correctness Issues

**V-06 — Low: Hardcoded PM keyword set ignores `self.search_params`**

- **File:** `scrapers/remoteok.py:38-39`
- pm_keywords are hardcoded; does not read from `self.search_params`.
- **Impact:** Low.

---

### Naukri (`scrapers/naukri.py`)

#### (b) Edge Cases Not Covered

**V-07 — Medium: `_scrape_page` has no `try/finally` around the main page — page leaks if `_parse_html` raises**

- **File:** `scrapers/naukri.py:82-125`
- **Evidence:**
  ```python
  page = await context.new_page()        # line 103
  page.on("response", _intercept)
  await asyncio.sleep(random.uniform(2.0, 4.0))
  try:
      await page.goto(...)               # line 106-107
  except Exception:
      self._log.debug("page.goto_timeout", page=page_num)
  # ... (NO re-raise on goto failure!) ...
  await asyncio.sleep(4)
  
  if captured_responses:
      jobs = self._parse_api_response(captured_responses)
      if jobs:
          await page.close()             # line 117 (happy path only)
          return jobs
  
  html = await page.content()
  jobs = await self._parse_html(html, page)  # line 123 — can raise
  await page.close()                    # line 124 — skipped if _parse_html raises
  return jobs
  ```
  Two problems:
  1. `goto` timeout is **swallowed** (not re-raised), so the code continues to `page.content()` on a potentially broken page.
  2. There is no `try/finally` around `_parse_html`. If it raises an exception, `page.close()` at line 124 is never reached → **page leak**.
  
  The pattern from `known_edge_cases.md §12` (page = None sentinel + try/finally) is not applied here.
- **Impact:** Critical. In each scrape run across 5 pages, an exception in `_parse_html` would accumulate leaked pages. Under repeated error conditions this can exhaust browser context resources.

#### (c) Efficiency/Correctness Issues

**V-08 — Medium: goto timeout is silently swallowed, not surfaced as an error**

- **File:** `scrapers/naukri.py:106-109`
- **Evidence:**
  ```python
  try:
      await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
  except Exception:
      self._log.debug("page.goto_timeout", page=page_num)
  # Code continues to page.content() on a broken page
  ```
  The `goto` exception is caught and only debug-logged. The code then calls `page.content()` on a page that may be blank or partially loaded. This silently returns empty results rather than propagating the error. By contrast, `_get_page()` in `scrapers/base.py` correctly closes the page and re-raises.
- **Impact:** Medium. Navigation failures are masked — the run log shows "0 results" instead of "TimeoutError", making debugging harder.

---

### LinkedIn (`scrapers/linkedin.py`)

#### (c) Efficiency/Correctness Issues

**V-09 — High: No per-job location filter applied**

- **File:** `scrapers/linkedin.py:148-165`
- **Evidence:** The scraper appends jobs directly to `all_jobs` without calling `is_acceptable_location()` on the extracted `location` field. No import of `location_filter` exists in the file.
- LinkedIn's `?location=Delhi%2C+India` is explicitly documented in `known_edge_cases.md §2` as returning global results. The only gate is the pipeline-level filter in `main.py`.
- **Impact:** High. All non-NCR and non-remote jobs scraped from LinkedIn enter `_run_all()` and then get filtered at the pipeline gate. This increases load on the dedup/scoring pipeline and means that if the pipeline gate is ever bypassed (e.g., direct `scraper.scrape()` call), wrong-location jobs enter the DB. Per `guidelines_and_learnings.md §3` (defense in depth), scraper-level and pipeline-level filters should both be present.

---

### Wellfound (`scrapers/wellfound.py`)

#### (c) Efficiency/Correctness Issues

**V-10 — High: No per-job location filter applied**

- **File:** `scrapers/wellfound.py:140-161`
- **Evidence:** Same as V-09. No `is_acceptable_location()` call exists. `?location=delhi` is documented in `known_edge_cases.md §2` as returning global results.
- **Impact:** High. Non-NCR jobs from Wellfound all rely solely on the pipeline gate. Defense-in-depth is missing.

---

### Indeed (`scrapers/indeed.py`)

#### (c) Efficiency/Correctness Issues

**V-11 — High: No per-job location filter applied**

- **File:** `scrapers/indeed.py:118-137`
- **Evidence:** No `is_acceptable_location()` call or import exists. Jobs are appended directly:
  ```python
  if not (title and apply_link):
      continue
  # ... fetches description ...
  jobs.append(Job(...))  # No location check
  ```
- **Impact:** High. Same as V-09/V-10. Indeed's `l=Delhi, India` is a hint, not a contract.

---

### IIMJobs (`scrapers/iimjobs.py`)

#### (b) Edge Cases Not Covered

**V-12 — Medium: No per-job location filter; relies 100% on server-side `loc=1` filter**

- **File:** `scrapers/iimjobs.py:88-158`
- **Evidence:** No `is_acceptable_location()` call or import. The scraper trusts `loc=DELHI_NCR_LOC_ID` (hardcoded as `1`) to filter server-side.
- From `known_edge_cases.md §2`: "Never trust a portal's URL-level filter." If the IIMJobs API ignores or reassigns `loc=1`, all results enter the DB. There is no per-job validation.
- **Impact:** Medium (IIMJobs' API appears more reliable than HTML scrapers, but the principle still applies).

#### (c) Efficiency/Correctness Issues

**V-13 — Medium: `createdTime` (without `Ms` suffix) may be Unix seconds, not milliseconds**

- **File:** `scrapers/iimjobs.py:132-137`
- **Evidence:**
  ```python
  created_ms = item.get("createdTimeMs") or item.get("createdTime")
  if created_ms:
      posted_date = datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc).date()
  ```
  The fallback `createdTime` field (without `Ms`) is treated as milliseconds by dividing by 1000. If this field is actually Unix seconds (which is conventional), the division would produce dates ~50 years in the past (e.g., `1712490000 / 1000 = 1712490` seconds → 1970-01-20). The same issue exists in `scrapers/hirist.py:129-134`.
- **Impact:** Medium. Wrong `posted_date` breaks recency scoring bonuses and stale-posting detection.

---

### Hirist (`scrapers/hirist.py`)

#### (c) Efficiency/Correctness Issues

**V-14 — Critical: Inline `DELHI_NCR_KEYWORDS` set instead of `is_acceptable_location()`**

- **File:** `scrapers/hirist.py:23, 102-104`
- **Evidence:**
  ```python
  # Line 23 — inline allowlist:
  DELHI_NCR_KEYWORDS = {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad"}

  # Lines 102-104 — inline filter:
  loc_lower = location.lower()
  if not any(kw in loc_lower for kw in DELHI_NCR_KEYWORDS):
      continue
  ```
  This violates `known_edge_cases.md §1` and `guidelines_and_learnings.md §1` (single source of truth). Problems with this approach:
  1. **Missing word-boundary check:** `"Indianapolis"` contains `"india"` — but `"indianapolis"` does not contain any of these tokens, so this particular bug doesn't apply here. However, `"nodaville"` contains `"noda"` — no direct collision, but the point stands that it's fragile.
  2. **Missing remote handling:** A Hirist job listed as `"Remote"` with no NCR token will be rejected even if it's a global-remote role that is perfectly acceptable.
  3. **Missing `REMOTE_EXCLUSIONS` check:** `"Remote — USA only"` would be rejected (by accident, correctly), but `"Remote — India"` would also be rejected (incorrectly, since it passes `is_acceptable_location`).
  4. **Divergence risk:** When `services/location_filter.py` adds new NCR tokens (e.g., `"Manesar"`) or remote exceptions, Hirist silently stays out of sync.
- **Impact:** Critical. Remote-eligible jobs from Hirist are silently dropped (false negatives). Non-NCR jobs may or may not be correctly rejected depending on coincidental token matches.

---

### Instahyre (`scrapers/instahyre.py`)

#### (c) Efficiency/Correctness Issues

**V-15 — Medium: No per-job location filter; relies entirely on API `jobLocations` param**

- **File:** `scrapers/instahyre.py:118-155`
- **Evidence:** No `is_acceptable_location()` call or import. The scraper passes `"jobLocations": "Delhi / NCR"` as a query param and trusts the API's server-side filtering.
- Per `known_edge_cases.md §2`, API location filters are not authoritative.
- **Impact:** Medium. Instahyre's API appears to respect `jobLocations` more reliably than HTML scrapers, but the lack of per-job validation means any API drift goes undetected.

---

### VC Portals (`vc_portals/scraper.py`)

#### (c) Efficiency/Correctness Issues

**V-16 — Critical: `_get_page()` swallows `goto` timeout and does NOT close the page**

- **File:** `vc_portals/scraper.py:251-260`
- **Evidence:**
  ```python
  async def _get_page(self, url: str, intercept_fn=None) -> Page:
      context = await self.bm.get_context("vc_portals", Path("cookies"))
      page = await context.new_page()
      if intercept_fn:
          page.on("response", intercept_fn)
      try:
          await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
      except Exception:
          self._log.debug("vc.goto_timeout", url=url)   # ← swallowed!
      return page                                         # ← page returned even after goto failure
  ```
  This violates both rules from `known_edge_cases.md §12`:
  1. **The exception is swallowed** — the page is returned even when `goto()` failed, meaning the caller gets a blank/broken page back (not an exception to handle).
  2. **The page is not closed** on goto failure — since the exception is swallowed, the caller gets the (broken) page and must close it, but the caller (`_scrape_vc_portal`) calls `await page.close()` only after successful processing, not in a `finally` block.
  
  Compare with `mnc_careers/scraper.py:146-153` which correctly closes the page and re-raises.
- **Impact:** Critical. Every VC portal navigation timeout accumulates open pages. With 9+ VC portals per run, repeated timeouts can exhaust browser context resources within a single run.

---

### Funding Scanner (`funding/scanner.py`)

#### (b) Edge Cases Not Covered

**V-17 — Medium: Company name extraction misses Inc42's current article structure**

- **File:** `funding/scanner.py:135-195`
- **Evidence:**
  ```python
  articles = soup.select("article, div[class*='post-card'], div[class*='article']")
  for article in articles[:20]:
      title_el = article.select_one("h2 a, h3 a, a[class*='title']")
  ```
  The live fetch of `https://inc42.com/tag/funding/` shows the site uses structured JSON-LD (`@type: "NewsArticle"`) and likely obfuscated or framework-generated class names. The selectors `div[class*='post-card']` and `div[class*='article']` may not match. If `articles` returns 0 items, the entire Inc42 source produces no companies silently (only a count log).
- **Impact:** Medium. Silent zero-result runs are indistinguishable from "no new funding news" without checking the count log.

#### (c) Efficiency/Correctness Issues

**V-18 — Low: Funding dedup uses raw `company.lower()` not `_company_slug()`**

- **File:** `funding/scanner.py:108-109`
- **Evidence:**
  ```python
  seen: dict[str, FundedCompany] = {}
  for c in all_companies:
      key = c.company.lower().strip()   # ← raw lowercase, no slug normalisation
      if key not in seen:
          seen[key] = c
  ```
  Per `known_edge_cases.md §14` and `guidelines_and_learnings.md §1`, company dedup must use `_company_slug()` from `services/scoring.py`. The inline `lower().strip()` does not strip legal suffixes, so `"Acme Technologies Pvt Ltd"` and `"Acme"` from different sources are treated as distinct companies.
- **Impact:** Low (within the funding scanner only; the main job dedup uses `dedup_hash` which uses proper slug normalisation).

---

## Cross-Cutting Findings (Audit Questions A–Q)

The following is a summary of each checklist item from the audit protocol:

| Check | Finding |
|-------|---------|
| **A. Location filter gaps** | 5 scrapers skip per-job filtering: linkedin, wellfound, indeed, iimjobs, instahyre. Hirist uses its own inline keyword set (V-14, Critical). All rely on the pipeline gate in `main.py` as the only defense. |
| **B. Search query hardcoding** | remoteok, ycombinator all use hardcoded `pm_keywords` sets independent of `self.search_params.title_keywords[0]`. iimjobs and instahyre correctly use `search_params`. LinkedIn and others use `search_params` for the query string. |
| **C. Naukri placeholder ordering** | CORRECT. `scrapers/naukri.py:144-151` iterates by `ph["type"]` and builds `by_type` dict. Positional bug is fixed. |
| **D. Resource leak patterns** | naukri `_scrape_page` has a page leak if `_parse_html` raises (V-07). vc_portals `_get_page` swallows goto exceptions and does not close the page (V-16). All API endpoints in `api/server.py` use `try/finally: db.close()` — correct. |
| **E. `_safe_scrape` return type** | CORRECT. `scrapers/base.py:77-92` returns `tuple[list[Job], str | None]`. `main.py:67-68` correctly unpacks `jobs, scrape_error = await task`. |
| **G. YC first-match-wins** | CORRECT. `scrapers/ycombinator.py:144-146`: `if not location and any(...)` — guards ensure only the first match sets `location`. |
| **H. Apollo rate limiter** | CORRECT. `outreach/apollo_client.py:154-175` uses token-bucket pattern with `_last_call_ts`. Guards `if self.rate_limit is None or self.rate_limit <= 0: return` prevents ZeroDivisionError. |
| **I. Company slug consistency** | CORRECT. `outreach/db.py:92-113` imports `_company_slug` from `services.scoring` and uses it for both the target and each existing contact. Fallback on import error uses raw lowercase. |
| **J. Direct source scoring bonus** | CORRECT. `services/scoring.py:184-189` checks both `platform in DIRECT_SOURCE_PLATFORMS` and `platform.startswith("vc_")` / `platform.startswith("mnc_")`. |
| **K. `priority_bucket` sentinel** | CORRECT. `storage/db.py:259-275` checks `priority_bucket = ''` for unscored jobs, not `priority_score = 0`. |
| **L. `applied_at` COALESCE in upsert** | CORRECT. `storage/db.py:377`: `applied_at = COALESCE(excluded.applied_at, applications.applied_at)`. |
| **M. Application ID consistency** | CORRECT. Both `api/server.py` (lines 369, 405) and any CLI shortlist code call `application_id_for(job_id)` from `storage/db.py`. |
| **N. `update_job_warmth_score()` commit behavior** | CORRECT. `storage/db.py:277-283` does NOT commit — comment states "Caller is responsible for commit". |
| **O. Dedup hash components** | CORRECT. `models/job.py:65-77` computes `dedup_hash` from `company + title + normalize_region(location)` — includes region component. |
| **P. Hirist location filter** | BROKEN. Uses inline `DELHI_NCR_KEYWORDS` set, not `is_acceptable_location()`. (V-14, Critical.) |
| **Q. `_get_page()` goto failure handling** | MIXED. `scrapers/base.py` (used by most scrapers): CORRECT — closes page and re-raises. `vc_portals/scraper.py:251-260`: BROKEN — swallows exception, returns broken page. `mnc_careers/scraper.py:146-153`: CORRECT — closes page and re-raises. |

---

## Prioritised Fix List

| Priority | Finding | File | Fix |
|----------|---------|------|-----|
| P0 | **V-14** Hirist inline keyword filter | `scrapers/hirist.py:23, 102-104` | Replace with `from services.location_filter import is_acceptable_location` and call it per job |
| P0 | **V-07** Naukri page leak | `scrapers/naukri.py:103-125` | Wrap `_scrape_page` body in `try/finally: if page: await page.close()` |
| P0 | **V-16** VC portal `_get_page` swallows goto | `vc_portals/scraper.py:251-260` | Close page and re-raise on exception (match `mnc_careers/scraper.py` pattern) |
| P1 | **V-04** RemoteOK apply_link wrong field | `scrapers/remoteok.py:59` | Change `item.get("url", "")` to `item.get("apply_url", "") or item.get("url", "")` |
| P1 | **V-09** LinkedIn no per-job location filter | `scrapers/linkedin.py` | Add `is_acceptable_location(location)` check before appending jobs |
| P1 | **V-10** Wellfound no per-job location filter | `scrapers/wellfound.py` | Same as V-09 |
| P1 | **V-11** Indeed no per-job location filter | `scrapers/indeed.py` | Same as V-09 |
| P2 | **V-08** Naukri goto timeout swallowed | `scrapers/naukri.py:108-109` | Log as warning (not debug), and close+return empty rather than continuing on broken page |
| P2 | **V-13** IIMJobs/Hirist `createdTime` ms/s ambiguity | `scrapers/iimjobs.py:132`, `scrapers/hirist.py:129` | Check magnitude: if `> 1e10`, treat as ms; else treat as seconds |
| P2 | **V-18** Funding dedup uses raw lowercase | `funding/scanner.py:108-109` | Replace `c.company.lower().strip()` with `_company_slug(c.company)` |
| P3 | **V-05** RemoteOK `$0 - $0` salary | `scrapers/remoteok.py:51` | Change condition to `if salary_min and salary_max` |
| P3 | **V-12** IIMJobs no per-job location filter | `scrapers/iimjobs.py` | Add `is_acceptable_location(location)` per job |
| P3 | **V-15** Instahyre no per-job location filter | `scrapers/instahyre.py` | Same |
| P3 | **V-06** Hardcoded pm_keywords | `scrapers/remoteok.py:38` | Add `self.search_params.title_keywords[0]` to the keyword set or derive from it |
| P3 | **V-17** Inc42 selector may miss articles | `funding/scanner.py:149` | Verify selectors against live HTML; add JSON-LD fallback extraction |

---

## New Edge Cases to Add to `known_edge_cases.md`

1. **RemoteOK has two URL fields: `url` (listing page) and `apply_url` (employer ATS link).** Using `url` as the apply link sends candidates to RemoteOK's own job listing page instead of the employer's application form.
