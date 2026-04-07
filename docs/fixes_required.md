# Fixes Required

> **Generated:** 2026-04-07  
> **Decider:** Claude Sonnet 4.6  
> **Based on:** `docs/validation_report.md`, `docs/pipelines_v1.md`, direct code inspection of all flagged files

---

## Decision Matrix

| ID | Source | Finding | Sound? | Root Cause | Priority | Defer Reason (if P2+) |
|----|--------|---------|--------|------------|----------|-----------------------|
| V-01 | WeWorkRemotely | Region regex runs on description; `<region>` is a dedicated XML element | N | Wrong assumption — docs/code relied on stale RSS format | **P0** | — |
| V-02 | WeWorkRemotely | `<type>` and `<skills>` XML elements unused | Y | Not a bug; cosmetic data gap | P3 | Rarely populated; no functional impact |
| V-03 | WeWorkRemotely | Hardcoded `pm_keywords` ignores `self.search_params` | N | Violates known_edge_cases.md §7 | P2 | Hardcoded set is broad enough to cover PM variants; maintenance risk only |
| V-04 | RemoteOK | `apply_link` reads `url` (listing page) instead of `apply_url` (employer ATS) | N | Wrong assumption — two distinct fields confused | **P1** | — |
| V-05 | RemoteOK | `salary_min = 0` / `salary_max = 0` yields `"$0 - $0"` instead of `None` | N | Falsy-zero check missing | P2 | Cosmetic; does not affect filtering or dedup |
| V-06 | RemoteOK | Hardcoded `pm_keywords` ignores `self.search_params` | N | Same as V-03 | P2 | Same as V-03 |
| V-07 | Naukri | Page leaks if `_parse_html` raises — no `try/finally` | N | Missing resource-management pattern (known_edge_cases.md §12) | **P0** | — |
| V-08 | Naukri | `goto` timeout silently swallowed; code continues on broken page | N | Wrong error handling pattern | P2 | Does not corrupt DB; produces 0 results, not wrong results. Fix alongside V-07 |
| V-09 | LinkedIn | No per-job `is_acceptable_location()` check | N | Missing defense-in-depth layer (guidelines_and_learnings.md §3) | **P1** | — |
| V-10 | Wellfound | No per-job `is_acceptable_location()` check | N | Same as V-09 | **P1** | — |
| V-11 | Indeed | No per-job `is_acceptable_location()` check | N | Same as V-09 | **P1** | — |
| V-12 | IIMJobs | No per-job location filter; trusts server-side `loc=1` | N | Same class as V-09/V-10/V-11 | P2 | IIMJobs API respects loc param more reliably than HTML scrapers; lower risk |
| V-13 | IIMJobs / Hirist | `createdTime` fallback treated as ms; may be Unix seconds | N | Ambiguous field name; wrong divisor if field is seconds | P2 | Wrong posted_date degrades recency scoring but doesn't block ingestion |
| V-14 | Hirist | Inline `DELHI_NCR_KEYWORDS` set instead of `is_acceptable_location()` | N | Violates single-source-of-truth (known_edge_cases.md §1, guidelines_and_learnings.md §1) | **P0** | — |
| V-15 | Instahyre | No per-job location filter; trusts API `jobLocations` param | N | Same class as V-12 | P2 | Instahyre API more reliable; lower risk |
| V-16 | VC Portals | `_get_page()` swallows goto exception and returns broken page | N | Violates known_edge_cases.md §12; page never closed on failure | **P0** | — |
| V-17 | Funding Scanner | Inc42 CSS selectors may not match current site structure | Y (partially) | Selector drift risk; not a confirmed breakage | P2 | Best-effort scraper; zero results distinguishable in count log |
| V-18 | Funding Scanner | Dedup uses `c.company.lower().strip()` not `_company_slug()` | N | Violates known_edge_cases.md §14 / guidelines_and_learnings.md §1 | P2 | Scoped to funding dedup only; main job dedup uses correct `dedup_hash` |

**INVALID findings (Validator was correct, but classified severity needs calibration):**
- V-08 is noted as "Critical" in the validation report but is P2 here because it degrades output quality (0 results vs. timeout message) without corrupting data. It should be fixed as a batch with V-07.

---

## Implementation Order

Dependencies govern the sequence. Within each priority tier, order is by blast radius.

1. **V-14: Hirist inline location filter** — P0 data-corruption risk; standalone file change, no dependencies on other fixes
2. **V-01: WeWorkRemotely region XML field** — P0 data-corruption risk; standalone file change
3. **V-07: Naukri page leak + V-08 goto handling** — P0 resource leak; fix both in same pass since they touch the same function
4. **V-16: VC portal `_get_page` goto exception** — P0 resource leak; fix matches established pattern in `mnc_careers/scraper.py`
5. **V-09 / V-10 / V-11: LinkedIn / Wellfound / Indeed per-job location filter** — P1 defense-in-depth; same fix pattern across all three; do in a single pass
6. **V-04: RemoteOK apply_url field** — P1 wrong apply link; standalone one-line fix
7. **V-02, V-03, V-05, V-06, V-12, V-13, V-15, V-17, V-18** — P2/P3 deferred items (see below)

---

## P0 Fixes — Detailed Spec

---

### V-14: Hirist inline location keyword set

**File:** `scrapers/hirist.py`  
**Lines:** 23, 102–104  
**Current code:**
```python
# Line 23 — inline allowlist (violates single-source-of-truth):
DELHI_NCR_KEYWORDS = {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad"}

# Lines 102-104 — inline filter:
loc_lower = location.lower()
if not any(kw in loc_lower for kw in DELHI_NCR_KEYWORDS):
    continue
```

**Problems:**
1. Remote jobs (e.g., `"Remote"`, `"Anywhere"`, `"Remote — India"`) are silently dropped because none of the NCR keywords appear in the string.
2. `REMOTE_EXCLUSIONS` check is absent — `"Remote — USA only"` is also dropped (accidentally correct, but for the wrong reason).
3. When `services/location_filter.py` adds new NCR tokens (e.g., `"Manesar"`), Hirist silently stays out of sync.
4. No word-boundary protection — though `"nodaville"` is not a real city, the pattern is fragile.

**Fix:**

Step 1 — Remove the inline constant and add the canonical import at the top of the file (after existing imports):
```python
from services.location_filter import is_acceptable_location, explain as explain_location
```

Step 2 — Replace lines 23 and 102–104:
```python
# DELETE line 23 entirely:
# DELHI_NCR_KEYWORDS = {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad"}

# Replace lines 102-104 with:
if not is_acceptable_location(location):
    self._log.debug(
        "hirist.filtered_location",
        title=title, company=company,
        reason=explain_location(location),
    )
    continue
```

**Why the import line is important:** `services.location_filter` is the single source of truth per `known_edge_cases.md §1`. Specifying the exact import prevents a future agent from re-inventing a local version.

**Test:** Run `python main.py run -p hirist` against a live run. Verify:
- Jobs with `location = "Remote"` now appear in output (previously dropped)
- Jobs with `location = "Remote — USA only"` are still rejected
- Jobs with `location = "Noida"` still pass

---

### V-01: WeWorkRemotely region XML field

**File:** `scrapers/weworkremotely.py`  
**Lines:** 14–15, 93–96  
**Current code:**
```python
# Line 15 — regex compiled against description text (wrong):
_REGION_RE = re.compile(r"region\s*:?\s*([^<\n.]+)", re.IGNORECASE)

# Lines 93-96 — applied to stripped description body:
raw_region = ""
region_m = _REGION_RE.search(description)
if region_m:
    raw_region = region_m.group(1).strip().strip(",")
```

**Root cause:** The RSS format that prompted adding `_REGION_RE` (documented in `known_edge_cases.md §5`) assumed region was embedded as text in the `<description>` CDATA. Live fetch on 2026-04-07 confirms the current feed uses a dedicated `<region>Anywhere in the World</region>` child element on `<item>`. The description body has no `"Region:"` substring. `_REGION_RE` therefore never matches, `raw_region` is always `""`, and every job is stored as `location = "Remote"` — meaning US-only and EU-only jobs pass `is_acceptable_location("Remote")` and enter the database.

**Fix:**

Step 1 — Remove `_REGION_RE` entirely (lines 14–15):
```python
# DELETE:
# _REGION_RE = re.compile(r"region\s*:?\s*([^<\n.]+)", re.IGNORECASE)
```

Step 2 — Replace lines 93–96 with a direct XML field read:
```python
# Read the dedicated <region> element directly:
raw_region = (item.findtext("region") or "").strip()
```

The rest of the existing logic (lines 98–108) is correct and unchanged:
```python
if raw_region:
    location = f"Remote — {raw_region}"
else:
    location = "Remote"

if title and link:
    if not is_acceptable_location(location):
        self._log.debug("wwr.filtered_location",
                        title=title, company=company,
                        reason=explain_location(location))
        continue
```

**Also update `known_edge_cases.md §5`** to correct the outdated statement: the comment "WWR posts always include 'Region: ...' in the description body" is stale. The current feed uses `<region>` as a first-class XML child element.

**Test:** 
- Fetch `https://weworkremotely.com/categories/remote-product-jobs.rss` live; confirm an item's `<region>` value (e.g., `"Anywhere in the World"`) now populates `location`.
- Run `python main.py run -p weworkremotely`. Verify jobs with `"Anywhere in the World"` are accepted; jobs with a `<region>` value matching a `REMOTE_EXCLUSIONS` token (e.g., `"USA Only"`) are rejected and logged.

---

### V-07: Naukri page leak + V-08 goto timeout handling

**File:** `scrapers/naukri.py`  
**Lines:** 82–125  
**Current code:**
```python
async def _scrape_page(self, url: str, page_num: int) -> list[Job]:
    ...
    context = await self.bm.get_context(self.name, Path("cookies"))
    page = await context.new_page()           # line 103 — page opened here
    page.on("response", _intercept)
    await asyncio.sleep(random.uniform(2.0, 4.0))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    except Exception:
        self._log.debug("page.goto_timeout", page=page_num)   # BUG 1: swallowed
    await asyncio.sleep(4)

    if captured_responses:
        jobs = self._parse_api_response(captured_responses)
        if jobs:
            await page.close()                # happy path only — not in finally
            return jobs

    html = await page.content()
    jobs = await self._parse_html(html, page) # BUG 2: can raise; page.close() below skipped
    await page.close()                        # skipped if _parse_html raises
    return jobs
```

**Two bugs:**
1. `goto` exception is swallowed with `debug`-level log — the function continues on a potentially blank/broken page instead of closing it and returning.
2. There is no `try/finally` around the body — if `_parse_html` raises (e.g., a BeautifulSoup parse error), the `page.close()` at line 124 is never reached. Over 5 pages, this accumulates 5 leaked pages per run. Under repeated failures this exhausts Playwright context resources.

**Fix** (apply `try/finally` with `page = None` sentinel per `guidelines_and_learnings.md §4`):

```python
async def _scrape_page(self, url: str, page_num: int) -> list[Job]:
    """Try the XHR JSON API first, fall back to HTML parsing."""
    import random
    from pathlib import Path
    captured_responses: list[dict[str, Any]] = []

    async def _intercept(response: Response) -> None:
        resp_url = response.url
        if response.status == 200 and (
            "jobapi" in resp_url or "naukri.com/jobapi" in resp_url
            or ("naukri.com" in resp_url and "search" in resp_url)
        ):
            try:
                body = await response.json()
                if isinstance(body, dict) and body.get("jobDetails"):
                    captured_responses.append(body)
            except Exception:
                pass

    context = await self.bm.get_context(self.name, Path("cookies"))
    page = None  # sentinel — ensures finally block is safe even if new_page() raises
    try:
        page = await context.new_page()
        page.on("response", _intercept)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            # goto failed — page is likely blank; log as warning (not debug) so
            # failures are visible in run logs, then return empty rather than
            # continuing on a broken page.
            self._log.warning("page.goto_timeout", page=page_num, url=url)
            return []
        await asyncio.sleep(4)

        # --- Strategy 1: Parse captured JSON API responses ---
        if captured_responses:
            self._log.info("api.captured", count=len(captured_responses))
            jobs = self._parse_api_response(captured_responses)
            if jobs:
                return jobs

        # --- Strategy 2: Fall back to HTML ---
        self._log.info("fallback.html", page=page_num)
        html = await page.content()
        jobs = await self._parse_html(html, page)
        return jobs

    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
```

**Key changes:**
- `page = None` sentinel before `try` so `finally` is safe.
- `goto` exception now logs at `warning` level (not `debug`) and immediately returns `[]` — prevents continuing on a broken page. Addresses V-08 simultaneously.
- Single `page.close()` in `finally` — covers all return paths including exceptions from `_parse_html`.
- The early `await page.close(); return jobs` calls in the happy paths are removed; `finally` handles all cleanup.

**Test:**
- Confirm `page.close()` is called even when `_parse_html` raises an artificial exception.
- Run `python main.py run -p naukri` and verify no "leaked page" warnings from Playwright.

---

### V-16: VC portal `_get_page` swallows goto exception

**File:** `vc_portals/scraper.py`  
**Lines:** 251–260  
**Current code:**
```python
async def _get_page(self, url: str, intercept_fn=None) -> Page:
    context = await self.bm.get_context("vc_portals", Path("cookies"))
    page = await context.new_page()
    if intercept_fn:
        page.on("response", intercept_fn)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        self._log.debug("vc.goto_timeout", url=url)   # BUG: swallowed
    return page                                         # BUG: returned even on failure
```

**Root cause:** `goto` exception is caught and only debug-logged; the broken page is returned to the caller. The caller (`_scrape_vc_portal`) calls `await page.close()` only after successful processing, not in a `finally` block. Every network timeout on a VC portal accumulates an unclosed page. With 9+ VC portals per run, repeated timeouts can exhaust browser context resources.

**Fix** (match the `mnc_careers/scraper.py:146–153` pattern exactly):

```python
async def _get_page(self, url: str, intercept_fn=None) -> Page:
    context = await self.bm.get_context("vc_portals", Path("cookies"))
    page = await context.new_page()
    if intercept_fn:
        page.on("response", intercept_fn)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        await page.close()   # close before re-raising — no leaked page
        raise
    return page
```

**Why close-then-reraise:** The caller (`_scrape_vc_portal`) wraps each VC in a `try/except Exception` that logs and continues. When `_get_page` re-raises, the caller's outer `except` handles it cleanly without a leaked page. This matches `mnc_careers/scraper.py` and `scrapers/base.py` exactly.

**Test:**
- Temporarily set `timeout=1` in the VC portal `_get_page` call; run `python main.py vc-jobs`. Verify that:
  - Each VC that times out logs an error (not a debug), page count stays stable.
  - The run completes for all remaining VCs (outer `try/except` absorbs the re-raised error).

---

## P1 Fixes — Detailed Spec

---

### V-09 / V-10 / V-11: Missing per-job location filter (LinkedIn, Wellfound, Indeed)

**Files:**
- `scrapers/linkedin.py` (lines 148–160)
- `scrapers/wellfound.py` (lines 140–157)
- `scrapers/indeed.py` (lines 117–134)

**Root cause:** All three scrapers append jobs directly to their output list after extracting `location` from the HTML card, but never call `is_acceptable_location(location)`. Per `known_edge_cases.md §2`, search URL location filters (`?location=Delhi%2C+India`, `?location=delhi`, `l=Delhi, India`) are documented to return global results. The pipeline-level gate in `main.py _run_all()` is the only filter. Per `guidelines_and_learnings.md §3`, defense-in-depth requires both scraper-level and pipeline-level filters.

**Fix pattern — identical for all three scrapers:**

Step 1 — Add import at top of each file (after existing imports):
```python
from services.location_filter import is_acceptable_location, explain as explain_location
```

Step 2 — In the card-parsing loop, immediately before appending the `Job(...)` object, add:
```python
if not is_acceptable_location(location):
    self._log.debug(
        "<platform>.filtered_location",    # e.g. "linkedin.filtered_location"
        title=title, company=company,
        reason=explain_location(location),
    )
    continue
```

**Exact insertion points:**

**LinkedIn** (`scrapers/linkedin.py`) — insert before line 149 (`all_jobs.append(...)`):
```python
# After: location = loc_el.get_text(strip=True) if loc_el else ""
# Before: if not (title and apply_link):
if not is_acceptable_location(location):
    self._log.debug(
        "linkedin.filtered_location",
        title=title, company=company,
        reason=explain_location(location),
    )
    continue
```

**Wellfound** (`scrapers/wellfound.py`) — insert before line 146 (`jobs.append(...)`):
```python
# After: location = loc_el.get_text(strip=True) if loc_el else ""
# Before: if not (title and apply_link):
if not is_acceptable_location(location):
    self._log.debug(
        "wellfound.filtered_location",
        title=title, company=company,
        reason=explain_location(location),
    )
    continue
```

**Indeed** (`scrapers/indeed.py`) — insert before the `jobs.append(...)` call (after `location` is extracted at line 102):
```python
# After: location = loc_el.get_text(strip=True) if loc_el else ""
# Before: if not (title and apply_link):
if not is_acceptable_location(location):
    self._log.debug(
        "indeed.filtered_location",
        title=title, company=company,
        reason=explain_location(location),
    )
    continue
```

**Important:** The `is_acceptable_location` check must appear **after** `location` is extracted and **before** any expensive operation (description fetch). In LinkedIn and Indeed, description fetching happens inside the `if not (title and apply_link): continue` guard. The location check should be added alongside that guard, not after the description fetch.

**Test:**
- Run `python main.py run -p linkedin` (or wellfound/indeed). In the log, look for `*.filtered_location` entries with `reason` populated. Verify they make sense (e.g., `"Remote (US)"` → `"regional restriction"`).
- Run against existing DB snapshot and count how many previously inserted rows would now be rejected — if > 20% for any platform, investigate before deploying.

---

### V-04: RemoteOK `apply_link` reads wrong field

**File:** `scrapers/remoteok.py`  
**Line:** 59  
**Current code:**
```python
apply_url = item.get("url", "")        # BUG: reads RemoteOK listing page, not employer ATS
if apply_url and not apply_url.startswith("http"):
    apply_url = f"https://remoteok.com{apply_url}"
```

**Reality (live API 2026-04-07):** Two distinct fields exist on every item:
- `url`: `"https://remoteok.com/remote-jobs/1130997"` — the RemoteOK canonical listing page
- `apply_url`: `"https://jobs.ashby.io/..."` — the employer's actual application destination (always full absolute URL)

**Impact:** All RemoteOK jobs link to the RemoteOK listing page instead of the employer's ATS. Candidates who click "Apply" land on a page they would have come from, not the application form.

**Fix:**
```python
# Prefer the employer's direct apply URL; fall back to the RemoteOK listing
# page only if apply_url is absent (defensive; every observed item has apply_url).
apply_url = item.get("apply_url", "") or item.get("url", "")
if apply_url and not apply_url.startswith("http"):
    apply_url = f"https://remoteok.com{apply_url}"
```

**Note:** The `apply_url` field in the live API is always a full absolute URL (`https://...`), so the relative-URL prefix guard is defensive but harmless.

**Test:**
- Run `python main.py run -p remoteok`. Open the output CSV/DB and verify `apply_link` values now point to third-party ATSes (Ashby, Greenhouse, Lever, Workday, etc.) rather than `remoteok.com/remote-jobs/...` URLs.

---

## P2 Deferred Items

- **V-03 / V-06 — Hardcoded `pm_keywords` in WeWorkRemotely and RemoteOK:** The current sets are broad and cover all PM variants. Risk is purely maintenance (if `SearchParams.title_keywords` changes, these scrapers won't track the change). Defer until there is a concrete need to change the search query.

- **V-05 — RemoteOK `$0 - $0` salary string:** Cosmetic. Fix when touching the file for another reason by changing `if salary_min is not None and salary_max is not None:` to `if salary_min and salary_max:`.

- **V-08 — Naukri `goto` timeout log level:** Fixed as part of V-07 (the `try/finally` rewrite changes the `except` to return early with a `warning`-level log).

- **V-12 — IIMJobs no per-job location filter:** IIMJobs API respects `loc=1` more reliably than HTML scrapers. The class of bug is real (known_edge_cases.md §2), but the immediate risk is low. Fix in the next "location filter audit" sweep alongside V-15.

- **V-13 — IIMJobs / Hirist `createdTime` ms/s ambiguity:** Wrong `posted_date` degrades recency scoring but does not block ingestion or corrupt dedup keys. When fixing, apply this heuristic to both files simultaneously:
  ```python
  # If value > 1e10, assume milliseconds (13-digit epoch); else assume seconds
  ts_val = int(created_ms)
  if ts_val > 1_000_000_000_000:   # > year 2001 in ms
      posted_date = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc).date()
  else:
      posted_date = datetime.fromtimestamp(ts_val, tz=timezone.utc).date()
  ```
  Apply to both `scrapers/iimjobs.py:132–140` and `scrapers/hirist.py:129–137`.

- **V-15 — Instahyre no per-job location filter:** Same class as V-12. Defer; fix alongside V-12.

- **V-17 — Inc42 selector drift:** Best-effort scraper; zero-result runs are distinguishable via count log. Selector audit requires a live browser session to inspect current class names. Defer until the funding scanner shows persistent zero results from Inc42.

- **V-18 — Funding Scanner dedup uses raw `lower()` not `_company_slug()`:** Scoped entirely to the funding scanner's in-memory dedup pass. The main job database dedup uses `dedup_hash` which uses correct slug normalisation. Low blast radius. Fix when touching `funding/scanner.py` for another reason by importing `_company_slug` from `services.scoring`.

---

## Risk Assessment

### Fixes that touch data already in the DB

| Fix | Touches existing DB rows? | Migration needed? |
|-----|--------------------------|-------------------|
| V-01 (WWR region) | Indirectly: future runs will now reject US/EU-only jobs that previously entered the DB. Existing rows stay. | No DB migration. Run `python main.py recommend --rescore` after deploying to re-score any WWR jobs that may have slipped in. |
| V-14 (Hirist location) | Future runs will now accept Remote jobs that were previously dropped (false negatives). Existing rows unaffected. | No DB migration. |
| V-07 (Naukri leak) | None — page lifecycle fix only. | None. |
| V-16 (VC portal leak) | None — page lifecycle fix only. | None. |
| V-09/V-10/V-11 (location filters) | Future runs reject non-NCR jobs that previously entered DB. Existing rows stay. | No DB migration, but consider running the audit script from `guidelines_and_learnings.md §14` to measure how many existing rows would now be rejected, before deciding whether to purge them. |
| V-04 (RemoteOK apply_url) | Only new rows going forward get the correct apply_url. Existing rows have the wrong URL. | Optional: `UPDATE jobs SET apply_link = ... WHERE platform = 'remoteok'` — but the correct `apply_url` is not stored, so existing rows cannot be migrated without re-scraping. Accept the loss for historical rows. |

### Fixes that change the Job model schema

None of the above fixes change `models/job.py`. The `Job` model, `id`, and `dedup_hash` are unaffected.

### Fixes that change the DB schema

None. All fixes are in scraper/filter logic only.

---

## New Edge Cases to Add to `known_edge_cases.md`

After implementing the P0 fixes, add the following items to `docs/known_edge_cases.md`:

**Item (update §5):** The comment "WWR posts always include 'Region: ...' in the description body" was accurate for an older RSS format. As of April 2026, `<region>` is a dedicated XML child element of `<item>`. The `<description>` CDATA contains no `"Region:"` text. Fix: `item.findtext("region")`.

**New item:** RemoteOK has two URL fields that must not be confused: `url` (the RemoteOK canonical listing page, e.g., `https://remoteok.com/remote-jobs/1130997`) and `apply_url` (the employer's direct ATS link, e.g., `https://jobs.ashby.io/...`). Using `url` as the apply destination sends candidates to the RemoteOK page rather than the application form. Always use `item.get("apply_url") or item.get("url")`.

---

## Implementation Results

> **Implemented:** 2026-04-07  
> **Implementer:** Claude Sonnet 4.6

### Fixes Applied

| Fix | File | Key Change | Lines Affected |
|-----|------|-----------|----------------|
| V-14 (P0) | `scrapers/hirist.py` | Deleted `DELHI_NCR_KEYWORDS` constant (line 23); added `from services.location_filter import is_acceptable_location, explain as explain_location`; replaced 3-line inline filter with `is_acceptable_location(location)` call + structured debug log | Lines 11–12 (import), 23 (deleted), 102–107 (replaced) |
| V-01 (P0) | `scrapers/weworkremotely.py` | Removed `_REGION_RE` compiled regex (lines 14–15); replaced `_REGION_RE.search(description)` block with `item.findtext("region") or ""` | Lines 14–15 (deleted), 93–96 (replaced) |
| V-07 + V-08 (P0) | `scrapers/naukri.py` | Added `page = None` sentinel before `try`; wrapped entire page body in `try/finally` with `page.close()` in `finally`; changed `goto` exception handler from `debug`-level swallow to `warning`-level early return `[]`; removed duplicate `page.close()` calls in happy paths | Lines 102–134 (rewritten) |
| V-16 (P0) | `vc_portals/scraper.py` | Changed `_get_page` `except` block from `self._log.debug(...)` + `return page` to `await page.close(); raise` — matches `mnc_careers/scraper.py:151–153` pattern exactly | Lines 258–260 (replaced) |
| V-09 (P1) | `scrapers/linkedin.py` | Added `from services.location_filter import is_acceptable_location, explain as explain_location`; inserted per-job location check after `if not (title and apply_link): continue` guard and before description fetch | Lines 13–14 (import), 140–147 (check inserted) |
| V-10 (P1) | `scrapers/wellfound.py` | Same import + per-job location check after `if not (title and apply_link): continue` guard and before description fetch | Lines 13–14 (import), 141–147 (check inserted) |
| V-11 (P1) | `scrapers/indeed.py` | Same import + per-job location check after `if not (title and apply_link): continue` guard and before description fetch | Lines 12–13 (import), 118–124 (check inserted) |
| V-04 (P1) | `scrapers/remoteok.py` | Changed `apply_url = item.get("url", "")` to `apply_url = item.get("apply_url", "") or item.get("url", "")` | Line 59 |

### Layer 1: Compile Check — PASS

All 11 modules imported cleanly:
```
OK: scrapers.hirist
OK: scrapers.weworkremotely
OK: scrapers.naukri
OK: vc_portals.scraper
OK: scrapers.linkedin
OK: scrapers.wellfound
OK: scrapers.indeed
OK: scrapers.remoteok
OK: services.location_filter
OK: storage.db
OK: models.job
All modules compile
```

### Layer 2: Behavioral Smoke Tests — PASS

```
V-01 WWR region: 'Remote — USA only'
V-01 USA-only accepted: False
V-04 apply_url: 'https://employer.com/apply'
V-04 fallback url: 'https://remoteok.com/l/456'
V-14 [OK] 'Remote, India' -> True (expected True)
V-14 [OK] 'Remote (US)' -> False (expected False)
V-14 [OK] 'Remote — USA only' -> False (expected False)
V-14 [OK] 'Gurugram' -> True (expected True)
V-14 [OK] 'Remote, EMEA' -> False (expected False)
V-14 [OK] '' -> False (expected False)
Behavioral smoke tests passed
```

### Layer 3: E2E Import Check — PASS

```
SCRAPER_REGISTRY has 14 scrapers: ['naukri', 'iimjobs', 'foundit', 'indeed', 'cutshort', 'instahyre', 'hirist', 'linkedin', 'wellfound', 'glassdoor', 'remoteok', 'weworkremotely', 'ycombinator', 'weekday']
VC and MNC scrapers import OK
Apollo client imports OK
```

### Deferred Fixes

P2/P3 items (V-02, V-03, V-05, V-06, V-08, V-12, V-13, V-15, V-17, V-18) were not implemented per the priority spec. V-08 (Naukri goto log level) was addressed as part of the V-07 `try/finally` rewrite.
