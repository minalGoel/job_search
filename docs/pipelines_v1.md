# Ingestion Pipeline Documentation — v1

> **Purpose:** Pseudocode documentation of every ingestion source in the job search aggregator. Designed for consumption by the Validator agent. Each section mirrors the actual code precisely — field names, CSS selectors, and API paths are quoted verbatim.
>
> **Last updated:** 2026-04-07
>
> **Key cross-references:**
> - `docs/known_edge_cases.md` — data shape bugs that have already shipped (18 entries)
> - `docs/guidelines_and_learnings.md` — codified rules derived from those bugs
> - `services/location_filter.py` — single source of truth for location acceptance

---

## Foundation: Shared Infrastructure

### `models/job.py` — Job Model

Every ingestion source produces `Job` instances. Key computed fields:

- **`id`** — SHA256 of `"{platform}|{normalize(company)}|{normalize(title)}|{apply_link}"`, truncated to 16 hex chars. Auto-computed on `model_validator(mode="after")`.
- **`dedup_hash`** — SHA256 of `"{company_stripped}|{title_stripped}|{region}"` where:
  - `company_stripped` = `_strip_company_suffixes()` (removes pvt, ltd, inc, technologies, solutions, india, services, labs, etc.)
  - `title_stripped` = `_strip_title_decorators()` (removes `- Remote`, `- Hybrid`, `- Delhi`, etc.)
  - `region` = `services.location_filter.normalize_region(location)` (maps to canonical `"delhi-ncr"`, `"remote"`, etc.)

**Critical assumption:** `dedup_hash` includes a location component so that London-Expedia and Delhi-Expedia do not collide. See known_edge_cases.md §5.

### `scrapers/base.py` — BaseScraper

All scrapers extend `BaseScraper`. Key behavior:

**`_get_page(url)`:**
```
context = bm.get_context(platform, Path("cookies"))
page = context.new_page()
sleep(random 2.0–5.0 seconds)   # fingerprint delay
try:
    page.goto(url, wait_until="domcontentloaded")
except:
    page.close()    # prevents page leaks on timeout — see known_edge_cases.md §12
    raise
return page
```

**`_safe_scrape()`:**
```
try:
    jobs = await self.scrape()
    return (jobs, None)
except Exception as exc:
    return ([], f"{type(exc).__name__}: {exc}")
```
Returns a tuple so the orchestrator can record the true failure reason in `runs` table. See known_edge_cases.md §16.

### `browser/context.py` — BrowserManager

- Launches Chromium with `--headless=new` (newer headless mode, harder to detect)
- Per-platform contexts cached in `self._contexts[platform]`
- Loads cookies from `cookies/{platform}.json` if it exists (Playwright storage state format)
- Applies `playwright-stealth` using defensive shim that tries `apply_stealth` then `apply_stealth_async` — handles v1/v2 API churn. See known_edge_cases.md §15.
- User-agent is randomly chosen from 6 Chrome variants

### `services/location_filter.py` — Location Filter

Single source of truth for location acceptance (see known_edge_cases.md §1, §2).

**`is_acceptable_location(loc)`** — returns `True` if:
1. Contains NCR tokens: `delhi ncr`, `delhi`, `ncr`, `gurugram`, `gurgaon`, `noida`, `faridabad`, `ghaziabad`, `new delhi`
2. Contains remote tokens (`remote`, `anywhere`, `worldwide`, `global`, `wfh`, etc.) — UNLESS blocked by:
   - `REMOTE_EXCLUSIONS`: `us only`, `eu only`, `uk only`, `emea`, `(us)`, `(uk)`, etc.
   - `INDIA_NON_NCR_CITIES`: bangalore, mumbai, hyderabad, chennai, pune, etc.
   - `NON_INDIA_CITIES`: london, berlin, san francisco, etc.
3. Contains bare `\bindia\b` word (country-level posting)

Returns `False` for empty/None locations. Uses `\bindia\b` regex to avoid "Indianapolis" false positive.

**`normalize_region(loc)`** — produces dedup-friendly key:
- NCR tokens → `"delhi-ncr"`
- Remote (no non-India city) → `"remote"`
- India non-NCR city → city name
- Otherwise → first 32 chars of normalized string

---

## 1. RemoteOK (`scrapers/remoteok.py`)

### Overview
- Type: JSON API (free public endpoint)
- Requires Playwright: No
- Requires auth: No

### Request Construction
- URL: `https://remoteok.com/api` (single endpoint, no pagination)
- Auth: none
- Headers: `User-Agent: JobSearchAggregator/1.0`
- Pagination: none — full catalog returned in a single response
- Rate limiting: none implemented; single call per run

### Pseudocode
```
GET https://remoteok.com/api
  headers: {User-Agent: "JobSearchAggregator/1.0"}
  timeout: 30s

data = response.json()
listings = data[1:]   # first item is legal disclaimer; skip

pm_keywords = {"product manager", "product management", "senior pm",
               "head of product", "director product", "vp product"}

for item in listings:
    position = item["position"]
    if not any(kw in position.lower() for kw in pm_keywords):
        continue

    company  = item["company"]
    location = item["location"] or "Remote"
    salary   = "$salary_min - $salary_max" if both present else None
    tags     = item["tags"] if list else []
    apply_url = item["url"]
    if apply_url doesn't start with "http":
        apply_url = "https://remoteok.com" + apply_url
    description = strip_html(item["description"])[:2000]
    date_str = item["date"]
    posted_date = parse ISO date (replace Z with +00:00)

    final_location = location.strip() or "Remote"
    if not is_acceptable_location(final_location):
        log debug with explain_location(); continue

    if position and company:
        yield Job(platform="remoteok", ...)
```

### Schema Mapping
| Raw field | Target Job field | Extraction method | Type assumption |
|-----------|-----------------|-------------------|-----------------|
| `position` | `title` | `item.get("position", "")` | string |
| `company` | `company` | `item.get("company", "")` | string |
| `location` | `location` | `item.get("location", "Remote")` | string; defaults to "Remote" if absent |
| `salary_min`, `salary_max` | `salary` | formatted as `"$min - $max"` | both must be non-None for salary to be set |
| `tags` | `skills` | `item.get("tags", [])` if list | list of strings; non-list becomes `[]` |
| `url` | `apply_link` | `item.get("url", "")`, relative prefixed with `https://remoteok.com` | string |
| `description` | `description` | HTML stripped, truncated to 2000 chars | HTML string |
| `date` | `posted_date` | `datetime.fromisoformat(date.replace("Z", "+00:00")).date()` | ISO 8601 string |

### Explicit Assumptions
- Assumes first element of the JSON array is a legal notice and should be skipped (hardcoded `data[1:]`)
- Assumes `salary_min` and `salary_max` when present are numeric values suitable for `${}` formatting
- Assumes `tags` field, when present, is a flat list of strings
- Assumes `date` is ISO 8601 format when present
- Assumes remote jobs with no explicit location restriction are acceptable (defaults location to "Remote")
- Assumes `url` relative paths are relative to `https://remoteok.com`

### Known Failure Modes
- If RemoteOK changes the API response to remove the legal notice header, `data[1:]` skips the first real job
- If `salary_min` or `salary_max` are 0 (falsy), the salary is set to `None` (0-salary roles silently have no salary)
- If `tags` is a dict instead of a list, becomes `[]` (no skills extracted)
- If the API returns non-JSON (e.g., Cloudflare challenge page), `resp.json()` raises an exception which propagates up and is caught by `_safe_scrape()`
- No page limit — all PM listings globally are ingested; location filter is the only gate
- Date format failures silently set `posted_date = None`
- No title-keyword filter respects `self.search_params`; pm_keywords are hardcoded (see known_edge_cases.md §7)

### Null/Missing Field Handling
- `location` absent → defaults to `"Remote"` — this is intentional for a remote-first board
- `salary_min`/`salary_max` absent → `salary = None`
- `tags` absent → `skills = []`
- `date` absent → `posted_date = None`
- `description` absent → empty string
- If `position` or `company` is empty string → item is skipped (guard: `if position and company`)

---

## 2. Naukri (`scrapers/naukri.py`)

### Overview
- Type: XHR JSON API interception + HTML fallback
- Requires Playwright: Yes
- Requires auth: No

### Request Construction
- Base URL pattern: `https://www.naukri.com/{keyword}-jobs-in-delhi-ncr`
  - `keyword` = `"-".join(search_params.title_keywords[0].lower().split())` (e.g., `"product-manager"`)
- Query params: `experience={min}`, `salary={min_ctc_lpa}`, `pageNo={page}` (page > 1 only)
- Strategy 1 (preferred): intercept XHR responses where URL contains `"jobapi"` or `("naukri.com" + "search")` and body has `jobDetails` key
- Strategy 2 (fallback): parse HTML with BeautifulSoup after page load
- Pagination: up to `MAX_PAGES = 5`; stops early if a page returns 0 jobs
- Rate limiting: `asyncio.sleep(2)` between pages; `asyncio.sleep(random 2.0–4.0)` before navigation

### Pseudocode
```
for page_num in 1..MAX_PAGES:
    url = build_search_url(page_num)
    captured_responses = []

    # Register intercept BEFORE navigation
    page.on("response", intercept_handler)

    goto url, wait_until="domcontentloaded", timeout=20000
    sleep(4 seconds)    # wait for XHR to fire

    if captured_responses:
        jobs = _parse_api_response(captured_responses)
        if jobs:
            page.close(); return jobs

    # HTML fallback
    html = page.content()
    jobs = _parse_html(html, page)
    page.close()
    return jobs

def _parse_api_response(responses):
    for resp in responses:
        job_details = resp["jobDetails"]
        for item in job_details:
            title   = item["title"]
            company = item["companyName"]

            # CRITICAL: iterate by type, never by index
            by_type = {}
            for ph in item.get("placeholders", []):
                by_type[ph["type"]] = ph["label"]
            location = by_type.get("location", "")
            salary   = by_type.get("salary") or None
            # experience discarded

            raw_skills = item["tagsAndSkills"]
            if isinstance(raw_skills, str):
                skills = [s.strip() for s in raw_skills.split(",")]
            elif isinstance(raw_skills, list):
                skills = [s["label"] if dict else str(s) for s in raw_skills]

            apply_link = item["jdURL"]
            if not apply_link.startswith("http"):
                apply_link = "https://www.naukri.com" + apply_link

            posted_date = _parse_relative_date(item["footerPlaceholderLabel"])
            description = item["jobDescription"]

            if title and company and apply_link:
                yield Job(platform="naukri", ...)

def _parse_html(html, page):
    cards = soup.select("div.cust-job-tuple")
           or soup.select("div.srp-jobtuple-wrapper")
           or soup.select("div[class*='job-tuple']")

    for card in cards:
        title     = card.select_one("a.title").text
        apply_link = card.select_one("a.title")["href"]
        company   = card.select_one("a.comp-name, span.comp-dtls-wrap a").text
        location  = card.select_one("span.locWdth, span.loc-wrap").text
        salary    = card.select_one("span.sal-wrap, span[class*='sal']").text
        skills    = [s.text for s in card.select("span.dot-gt.tag-li, li.tag-li")]
        posted_date = _parse_relative_date(card.select_one("span.job-post-day").text)
        description = _fetch_description(apply_link)   # separate page load
        yield Job(platform="naukri", salary=None if salary=="Not disclosed" else salary, ...)

def _parse_relative_date(text):
    "just now" / "today"  → date.today()
    "N days ago"           → today - N days
    "N weeks ago"          → today - N*7 days
    "N months ago"         → today - N*30 days
    "N hours ago"          → today
    else                   → None

def _fetch_description(url):
    # Opens a new page via _get_page(), has try/finally to close it
    jd_el = soup.select_one(
        "div[class*='job-desc'], div[class*='jd-desc'], "
        "section[class*='job-desc'], div.dang-inner-html"
    )
    return jd_el.get_text(separator="\n", strip=True) or ""
```

### Schema Mapping (API path)
| Raw field | Target Job field | Extraction method | Type assumption |
|-----------|-----------------|-------------------|-----------------|
| `title` | `title` | `item.get("title", "")` | string |
| `companyName` | `company` | `item.get("companyName", "")` | string |
| `placeholders[type=="location"].label` | `location` | iterate by type key | list of `{type, label}` dicts |
| `placeholders[type=="salary"].label` | `salary` | iterate by type key | list of `{type, label}` dicts |
| `tagsAndSkills` | `skills` | comma-split (str) or label extract (list) | string OR list of dicts or strings |
| `jdURL` | `apply_link` | relative → absolute with `naukri.com` prefix | string |
| `footerPlaceholderLabel` | `posted_date` | `_parse_relative_date()` | relative date string ("2 days ago") |
| `jobDescription` | `description` | raw string | string |

### Schema Mapping (HTML fallback path)
| CSS selector | Target Job field | Notes |
|--------------|-----------------|-------|
| `a.title` | `title`, `apply_link` | href is the apply link |
| `a.comp-name, span.comp-dtls-wrap a` | `company` | |
| `span.locWdth, span.loc-wrap` | `location` | |
| `span.sal-wrap, span[class*='sal']` | `salary` | filtered: `"Not disclosed"` → None |
| `span.dot-gt.tag-li, li.tag-li` | `skills` | list |
| `span.job-post-day` | `posted_date` | relative date text |

### Explicit Assumptions
- **API path:** Assumes `placeholders` is a list of `{type, label}` dicts and type can be `"location"`, `"salary"`, `"experience"`
- Assumes XHR responses matching URL pattern `("naukri.com" AND "search")` with `jobDetails` key are the correct API calls
- Assumes 4-second sleep after navigation is enough for XHR to complete
- Assumes `tagsAndSkills` is either a comma-separated string or a list of dicts with `label` key
- Assumes `jdURL` starts with `/` if relative
- Assumes HTML fallback card selectors remain stable
- Assumes `salary == "Not disclosed"` should be converted to None

### Known Failure Modes
- **Fixed bug (edge case §3):** Old code indexed `placeholders[0]` for location — this is an experience field in many responses. Fixed by type-keyed iteration.
- If `placeholders` order changes (experience no longer first), no breakage after the fix
- If Naukri enables CORS or changes XHR URL patterns, interception may capture 0 responses and always fall through to HTML
- HTML fallback card selectors will break on UI redesigns
- `_fetch_description()` in HTML path adds a full page load per job card — slow; N jobs = N extra navigations
- XHR intercept may fire multiple times (duplicate responses captured); `_parse_api_response` iterates all of them, potentially yielding duplicate jobs that dedup will catch
- `pageNo` parameter: absent for page 1 (works), present for pages 2+; if Naukri changes to 0-indexed pages, page 2 would be missing

### Null/Missing Field Handling
- `title`, `company`, `apply_link` all empty → item skipped
- `location` absent from placeholders → empty string
- `salary` absent → None
- `tagsAndSkills` None → `skills = []`
- `jobDescription` absent → empty string
- `footerPlaceholderLabel` absent → `posted_date = None`

---

## 4. IIMJobs (`scrapers/iimjobs.py`)

### Overview
- Type: Public REST JSON API (`gladiator.iimjobs.com`)
- Requires Playwright: No
- Requires auth: No

### Request Construction
- Base URL: `https://gladiator.iimjobs.com/job/search`
- Query params: `query=<title_keywords[0]>`, `page=<0-indexed>`, `loc=1` (Delhi NCR location ID), `posting=0`, `industry=""`
- Auth: Referer header `https://www.iimjobs.com/`
- Pagination: 0-indexed pages, up to `MAX_PAGES = 3` (3×50 = 150 max); stops early on empty `data` array or `hasMore == False`
- Rate limiting: `asyncio.sleep(1)` between pages

### Pseudocode
```
query = search_params.title_keywords[0]  # or "product manager" fallback

async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
    for page_num in 0..MAX_PAGES-1:
        params = {query, page: page_num, loc: 1, posting: 0, industry: ""}
        resp = client.get(BASE_URL + "?" + params)
        data = resp.json()

        raw_jobs = data["data"]
        if not raw_jobs: break

        for item in raw_jobs:
            title    = item["jobdesignation"] or item["title"]
            company  = item["companyData"]["companyName"]  # or str(companyData) if not dict
            locations = item["location"] or item["locations"] or []
            location = ", ".join(loc["name"] for loc in locations)
            salary   = f"{item['minSal']} - {item['maxSal']} LPA"  # or None if hidden or both 0
            tags     = item["tags"] or []
            skills   = [t["name"] for t in tags]  # or str(t) if not dict
            apply_link = item["jobDetailUrl"] or item["applyUrl"]
            if not apply_link.startswith("http"):
                apply_link = "https://www.iimjobs.com" + apply_link
            created_ms = item["createdTimeMs"] or item["createdTime"]
            posted_date = datetime.fromtimestamp(created_ms / 1000, tz=UTC).date()

            if title and company and apply_link:
                yield Job(platform="iimjobs", description="", ...)

        if not data["hasMore"]: break
        sleep(1)
```

### Schema Mapping
| Raw field | Target Job field | Extraction method | Type assumption |
|-----------|-----------------|-------------------|-----------------|
| `jobdesignation` or `title` | `title` | `or` fallback | string |
| `companyData.companyName` | `company` | nested dict access | dict with `companyName` key |
| `location` or `locations` | `location` | list of `{id, name}` dicts, joined by `, ` | list of dicts |
| `minSal`, `maxSal`, `hideSal` | `salary` | `"{min} - {max} LPA"` or None | integers; 0 treated as absent |
| `tags[].name` | `skills` | list of dicts with `name` key | list of `{id, name, isMandatory}` dicts |
| `jobDetailUrl` or `applyUrl` | `apply_link` | `or` fallback, relative → absolute | string |
| `createdTimeMs` or `createdTime` | `posted_date` | Unix milliseconds → UTC date | integer (ms) |

### Explicit Assumptions
- Assumes `DELHI_NCR_LOC_ID = 1` is the correct location filter ID for Delhi NCR
- Assumes `companyData` is either a dict or a scalar (handles both)
- Assumes `createdTimeMs` / `createdTime` is Unix milliseconds (divides by 1000)
- Assumes API is public and unauthenticated (no token needed)
- Assumes `hasMore` field controls pagination (stops when False)
- Description is always empty (`description=""`) — no description fetched
- `PAGE_SIZE = 50` is hardcoded in params but not used directly (the API controls result count)

### Known Failure Modes
- If `DELHI_NCR_LOC_ID` changes (Naukri/IIMJobs internal IDs can be reassigned), all results will be from a different location with no error
- `description=""` for all jobs — downstream scoring has no description text to work with
- If `companyData` is a nested dict with different key names, company becomes empty string
- If `minSal`/`maxSal` contain non-integer values, format string will include non-numeric text
- No secondary location validation — `is_acceptable_location()` is not called. Relies entirely on `loc=1` filter being server-side reliable (see known_edge_cases.md §2)
- `tagsAndSkills` is handled as `tags` — if IIMJobs changes field name, skills become `[]`
- `createdTime` without `Ms` suffix may be seconds (not milliseconds) — would produce wrong dates (~50 years off)

### Null/Missing Field Handling
- `jobdesignation` absent → falls back to `title`
- `companyData` absent → `company = ""`; item skipped if company empty
- `location`/`locations` absent → `location = ""`
- `minSal == 0 and maxSal == 0` → `salary = None`
- `hideSal == True` → `salary = None`
- `tags` absent → `skills = []`
- `jobDetailUrl`/`applyUrl` absent → `apply_link = ""`; item skipped
- `createdTimeMs`/`createdTime` absent → `posted_date = None`

---

## 5. LinkedIn (`scrapers/linkedin.py`)

### Overview
- Type: Guest HTML scraping (no login)
- Requires Playwright: Yes
- Requires auth: No (guest mode; auth wall detected and gracefully exited)

### Request Construction
- URL pattern: `https://www.linkedin.com/jobs/search/?keywords={keyword}&location=Delhi%2C+India&f_TPR=r2592000`
  - `keyword` = `"+".join(search_params.title_keywords[0].split())` (e.g., `"product+manager"`)
  - `f_TPR=r2592000` = past 30 days
  - Pagination: `&start={(page_num-1)*25}` for pages 2+
- Auth: none (guest mode); cookie jar loaded from `cookies/linkedin.json` if it exists
- Pagination: up to `MAX_PAGES = 3`
- Rate limiting: `asyncio.sleep(random 3.0–7.0)` before each page; `asyncio.sleep(random 3.0–6.0)` before each detail fetch

### Pseudocode
```
detail_fetches = 0

for page_num in 1..MAX_PAGES:
    sleep(random 3.0–7.0)
    page = _get_page(url)

    if "authwall" in page.url or "login" in page.url:
        page.close(); break

    # scroll to load lazy content
    for _ in 3:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        sleep(1.5)

    html = page.content()

    cards = soup.select("div.job-card-container")
           or soup.select("div.base-card")
           or soup.select("li.result-card")
           or soup.select("div[class*='job-search-card']")
           or soup.select("ul.jobs-search__results-list > li")

    if not cards: page.close(); break

    for card in cards:
        title    = card.select_one("a.job-card-container__link, .job-card-list__title, h3.base-search-card__title, h3[class*='title']").text
        link_el  = card.select_one("a.job-card-container__link, a.base-card__full-link, a[href*='/jobs/view/']")
        apply_link = link_el["href"].split("?")[0]   # strip tracking params
        company  = card.select_one(".job-card-container__primary-description, h4.base-search-card__subtitle, a[class*='subtitle']").text
        location = card.select_one(".job-card-container__metadata-item, span.job-search-card__location, span[class*='location']").text
        date_el  = card.select_one("time, span[class*='date'], span[class*='listdate']")
        date_text = date_el["datetime"] or date_el.text
        posted_date = _parse_relative_date(date_text)

        if not (title and apply_link): continue

        description = ""
        if detail_fetches < MAX_DETAIL_FETCHES:   # MAX_DETAIL_FETCHES = 10
            description = _fetch_description(apply_link)
            detail_fetches += 1

        yield Job(platform="linkedin", skills=[], ...)

    page.close()

def _fetch_description(url):
    sleep(random 3.0–6.0)
    page = _get_page(url)
    if "authwall" or "login" in page.url: return ""
    jd_el = soup.select_one(
        "div.show-more-less-html__markup, div[class*='description__text'], "
        "section[class*='description'] div"
    )
    return jd_el.get_text(separator="\n", strip=True) or ""
```

### Schema Mapping
| CSS selector | Target Job field | Notes |
|--------------|-----------------|-------|
| `a.job-card-container__link` (first match wins) | `title` | Multiple selector fallbacks |
| `a.job-card-container__link` href (stripped of `?...`) | `apply_link` | Query string removed |
| `.job-card-container__primary-description` | `company` | May be empty for unlisted companies |
| `.job-card-container__metadata-item` | `location` | |
| `time[datetime]` or `span[class*='date']` | `posted_date` | `datetime` attr preferred |

### Explicit Assumptions
- Assumes LinkedIn returns results in Delhi NCR order when `location=Delhi%2C+India` is set (known to return global results — see known_edge_cases.md §2)
- Assumes auth wall is detectable by `"authwall"` or `"login"` appearing in the URL
- Assumes scrolling 3 times loads all lazy content
- Assumes card selectors remain stable (confirmed April 2026)
- Assumes description is accessible without login for at least some jobs
- Assumes pagination increment is 25 per page
- `skills = []` always — LinkedIn guest search exposes no skills in card view

### Known Failure Modes
- **No location filter applied per-job** — LinkedIn location param is unreliable (see known_edge_cases.md §2). Jobs outside Delhi NCR will enter the DB if LinkedIn's ranking places them on the first 3 pages.
- Auth wall detection may miss new redirect patterns (e.g., `"/checkpoint/"`)
- LinkedIn changes HTML class names regularly; all card selectors can break simultaneously
- Detail fetch capped at `MAX_DETAIL_FETCHES = 10` — remaining jobs have empty description
- Tracking params stripped from apply_link (`split("?")[0]`) may break some job application links that require query params (rare)
- No backoff on 429 responses — Playwright navigates, gets rate-limited HTML, returns empty cards

### Null/Missing Field Handling
- `title` absent → empty string → item skipped
- `apply_link` absent → empty string → item skipped
- `company` absent → empty string; job still appended
- `location` absent → empty string; job still appended (no location filter applied!)
- `posted_date` parse failure → None
- `description` skipped if detail_fetches >= 10 → empty string

---

## 6. Wellfound (`scrapers/wellfound.py`)

### Overview
- Type: React SPA, HTML scraping after render
- Requires Playwright: Yes
- Requires auth: Yes (blank page in headless without login; `requires_login = True`)

### Request Construction
- URL pattern: `https://wellfound.com/jobs?role=product-manager&location=delhi`
  - Pagination: `&page={page_num}` for pages 2+
- Auth: session cookies from `cookies/wellfound.json`
- Pagination: up to `MAX_PAGES = 3`; stops early on empty cards
- Rate limiting: `asyncio.sleep(3)` between pages; `asyncio.sleep(2)` after page load

### Pseudocode
```
for page_num in 1..MAX_PAGES:
    url = build_search_url(page_num)
    jobs = _scrape_page(url)
    if not jobs: break
    sleep(3)

def _scrape_page(url):
    page = _get_page(url)
    page.wait_for_selector(
        "div[class*='job'], div[class*='styles_result'], a[class*='job-listing']",
        timeout=12000
    )
    sleep(2)
    html = page.content()

    if "captcha-delivery.com" or "challenge-platform" in html:
        log warning; page.close(); return []

    cards = soup.select("div[class*='styles_result']")
           or soup.select("div[class*='job-listing']")
           or soup.select("div[class*='StartupResult']")
           or soup.select("div[class*='browse-table-row']")

    for card in cards:
        title     = card.select_one("h2, h3, a[class*='title'], div[class*='title'], span[class*='title']").text
        link_el   = card.select_one("a[href*='/jobs/'], a[href*='/company/']")
        apply_link = "https://wellfound.com" + href if relative
        company   = card.select_one("h2, a[class*='company'], span[class*='company'], div[class*='company']").text
        location  = card.select_one("span[class*='location'], div[class*='location']").text
        salary    = card.select_one("span[class*='salary'], div[class*='compensation']").text
        skills    = [s.text for s in card.select("span[class*='skill'], span[class*='tag'], a[class*='tag']")]
        description = _fetch_description(apply_link)

        if title and apply_link:
            yield Job(platform="wellfound", posted_date=None, ...)
```

### Schema Mapping
| CSS selector | Target Job field | Notes |
|--------------|-----------------|-------|
| `h2, h3, a[class*='title']...` | `title` | Multiple fallbacks; first match wins |
| `a[href*='/jobs/']` | `apply_link` | Relative path prefixed with `https://wellfound.com` |
| `h2, a[class*='company']...` | `company` | Risk: `h2` selector matches both title and company |
| `span[class*='location']` | `location` | |
| `span[class*='salary']` | `salary` | Optional |
| `span[class*='skill']...` | `skills` | |

### Explicit Assumptions
- Assumes valid session cookies exist (blank page returned without auth)
- Assumes Cloudflare challenge is detectable by `"captcha-delivery.com"` or `"challenge-platform"` in HTML
- Assumes location URL param `?location=delhi` filters results (known to NOT filter — see known_edge_cases.md §2)
- Assumes `posted_date` is always None (no date extraction implemented)
- `h2` is used for both title and company selectors — depends on structural nesting being unambiguous

### Known Failure Modes
- **No location filter applied per-job** — `?location=delhi` does not restrict results (see known_edge_cases.md §2). Non-NCR jobs will be ingested.
- Cookie expiry returns a blank/redirect page; no explicit expiry detection (wait_for_selector will time out)
- Cloudflare bot detection may trigger intermittently even with valid cookies
- `h2` selector for company may match the job title element in some card layouts, producing title == company
- `posted_date` is always `None` for all Wellfound jobs
- React class names are hash-based (e.g., `styles_result__abc123`); `class*='styles_result'` is fragile against hash changes

### Null/Missing Field Handling
- `title` absent → empty string → item skipped
- `apply_link` absent → empty string → item skipped
- `company` absent → empty string; job still appended
- `location` absent → empty string; job still appended (no filter applied)
- `salary` absent → None
- `posted_date` always None

---

## 7. Indeed (`scrapers/indeed.py`)

### Overview
- Type: HTML scraping with Playwright (stealth)
- Requires Playwright: Yes
- Requires auth: No

### Request Construction
- URL pattern: `https://in.indeed.com/jobs?q={title_keywords[0]}&l=Delhi%2C+India&fromage=14&start={(page-1)*10}`
  - `fromage=14` = last 14 days
  - Pagination via `start` param, 10 results per page
- Auth: none
- Pagination: up to `MAX_PAGES = 5`; stops early on empty cards
- Rate limiting: `asyncio.sleep(3)` between pages; full `_get_page()` delay per detail fetch

### Pseudocode
```
for page_num in 1..MAX_PAGES:
    url = build_search_url(page_num)
    jobs = _scrape_page(url, page_num)
    if not jobs: break
    sleep(3)

def _scrape_page(url, page_num):
    page = _get_page(url)
    html = page.content()

    cards = soup.select("div.job_seen_beacon")
           or soup.select("div.jobsearch-ResultsList > div")
           or soup.select("div[class*='cardOutline']")
           or soup.select("li div[class*='result']")

    for card in cards:
        title_el   = card.select_one("h2.jobTitle a, a[data-jk]")
        title      = title_el.text
        href       = title_el["href"]
        apply_link = "https://in.indeed.com" + href if relative

        company  = card.select_one("[data-testid='company-name']").text
        location = card.select_one("[data-testid='text-location']").text
        salary   = card.select_one("div[class*='salary'], span[class*='salary'], div[class*='metadata'][class*='salary']").text
        date_el  = card.select_one("span[class*='date'], span[data-testid*='date']")
        posted_date = _parse_relative_date(date_el.text)

        if not (title and apply_link): continue

        description = _fetch_description(apply_link)   # per-job page load
        yield Job(platform="indeed", skills=[], ...)

def _fetch_description(url):
    # try/finally with page = None sentinel
    jd_el = soup.select_one(
        "div#jobDescriptionText, div[class*='jobsearch-jobDescriptionText'], "
        "div[class*='job-desc']"
    )
    return jd_el.get_text(separator="\n", strip=True) or ""
```

### Schema Mapping
| CSS selector | Target Job field | Notes |
|--------------|-----------------|-------|
| `h2.jobTitle a` or `a[data-jk]` | `title`, `apply_link` | href is relative |
| `[data-testid='company-name']` | `company` | |
| `[data-testid='text-location']` | `location` | |
| `div[class*='salary']` | `salary` | |
| `span[class*='date']` | `posted_date` | relative date text |

### Explicit Assumptions
- Assumes `in.indeed.com` is the correct India subdomain
- Assumes `data-testid` attributes (`company-name`, `text-location`) remain stable
- Assumes `?l=Delhi, India` filter returns Delhi NCR jobs (unreliable — see known_edge_cases.md §2)
- Assumes page size is 10 jobs (pagination via `start=(page-1)*10`)
- `skills = []` always — Indeed cards expose no skills

### Known Failure Modes
- **No per-job location filter** — location param `l=Delhi, India` not reliable. Non-NCR jobs can enter DB.
- Indeed has aggressive bot detection; may return CAPTCHA page or empty results without error
- All job detail pages require separate page loads — N jobs = N extra Playwright navigations
- `data-testid` selectors are more stable than class-based ones, but Indeed does change them
- If Indeed injects a "sponsored" result with different HTML structure, `div.job_seen_beacon` may miss it

### Null/Missing Field Handling
- `title` absent → empty → item skipped
- `apply_link` absent → empty → item skipped
- `company` absent → empty; job still appended
- `location` absent → empty; job still appended (no location filter)
- `salary` absent → None
- `posted_date` parse failure → None
- `description` fetch failure → empty string (try/finally ensures page closed)

---

## 8. Instahyre (`scrapers/instahyre.py`)

### Overview
- Type: Private REST JSON API with session cookies
- Requires Playwright: No (uses httpx with cookies)
- Requires auth: Yes (`sessionid` cookie required)

### Request Construction
- Base URL: `https://www.instahyre.com/api/v1/job_search`
- Query params: `isLandingPage=true`, `jobLocations=Delhi / NCR`, `skills=<title_keywords[0]>`, `job_type=0`, `source=opportunities`, `offset=<page*PAGE_SIZE>`, `limit=20`
- Auth: session cookies loaded from `cookies/instahyre.json` (Playwright storage state format)
- Pagination: offset-based, `PAGE_SIZE = 20`, up to `MAX_PAGES = 5` (100 jobs max); stops when `meta.next` is absent
- Rate limiting: `asyncio.sleep(1)` between pages

### Pseudocode
```
# Load cookies from Playwright storage state
cookies_data = json.loads(Path("cookies/instahyre.json").read_text())
cookies = {c["name"]: c["value"] for c in cookies_data["cookies"] if "instahyre" in c["domain"]}

if not cookies.get("sessionid"):
    log warning "session expired"; return []

skill_query = search_params.title_keywords[0]  # or "product management" fallback
location_query = "Delhi / NCR"  # hardcoded regardless of search_params.location

async with httpx.AsyncClient(headers=HEADERS, cookies=cookies) as client:
    for page_num in 0..MAX_PAGES-1:
        params = {skills: skill_query, jobLocations: location_query,
                  offset: page_num * PAGE_SIZE, limit: PAGE_SIZE, ...}
        resp = client.get(BASE_URL + "?" + params)

        if resp.status_code == 401:
            log warning "session expired"; break

        data = resp.json()
        raw_jobs = data["objects"]
        meta     = data["meta"]

        if not raw_jobs: break

        for item in raw_jobs:
            title    = item["title"].strip()
            employer = item["employer"] or {}
            company  = employer["company_name"].strip() if isinstance(employer, dict) else ""
            location = item["locations"]  # list → join; else str
            keywords = item["keywords"] or []
            skills   = [k for k in keywords if isinstance(k, str)]
            apply_link = item["public_url"]
            if not apply_link.startswith("http"):
                apply_link = "https://www.instahyre.com" + apply_link

            if title and company and apply_link:
                yield Job(platform="instahyre", salary=None, posted_date=None, description="", ...)

        if not meta["next"]: break
        sleep(1)
```

### Schema Mapping
| Raw field | Target Job field | Extraction method | Type assumption |
|-----------|-----------------|-------------------|-----------------|
| `title` | `title` | `item.get("title", "").strip()` | string |
| `employer.company_name` | `company` | nested dict; str fallback | dict with `company_name` key |
| `locations` | `location` | list → `", ".join()`; else `str()` | list of strings or scalar |
| `keywords` | `skills` | `[k for k in keywords if isinstance(k, str)]` | list of strings |
| `public_url` | `apply_link` | relative → absolute | string |

### Explicit Assumptions
- Assumes `cookies/instahyre.json` is a valid Playwright storage state file with a `cookies` array
- Assumes session cookie name is `sessionid`
- Assumes `jobLocations = "Delhi / NCR"` is the correct API string regardless of `search_params.location`
- Assumes `employer` is either a dict with `company_name` or a scalar
- Assumes `locations` when a list contains stringifiable items
- `salary = None` always — API doesn't expose salary
- `posted_date = None` always — API doesn't expose posting date
- `description = ""` always — no description fetched

### Known Failure Modes
- Cookie expiry detected only by `sessionid` absence or HTTP 401 — not by other session failure codes (403, redirect to login)
- Location `"Delhi / NCR"` is hardcoded — changing `search_params.location` to `"Gurugram"` has no effect
- `description = ""` for all jobs — scoring has no text to work with
- `posted_date = None` for all jobs — recency filter cannot apply
- If `employer` key is missing entirely, `company = ""`; item is then skipped (guard: `if title and company`)
- `meta["next"]` check stops pagination — if API changes pagination scheme (e.g., to `hasMore`), all pages after first will be missed

### Null/Missing Field Handling
- `sessionid` absent → returns `[]` immediately with warning log
- HTTP 401 → returns `[]` with warning log
- `employer` absent/None → `company = ""`; item skipped
- `locations` absent → empty string; job appended with empty location
- `keywords` absent → `skills = []`
- `public_url` absent → empty; item skipped

---

## 9. YCombinator (`scrapers/ycombinator.py`)

### Overview
- Type: Server-side rendered HTML (may lazy-load)
- Requires Playwright: Yes
- Requires auth: No

### Request Construction
- URL: `https://www.ycombinator.com/jobs/role/product-manager` (single page, no pagination)
- Auth: none
- Pagination: none (single page)
- Rate limiting: `_get_page()` base delay (2–5 seconds)

### Pseudocode
```
page = _get_page("https://www.ycombinator.com/jobs/role/product-manager")
page.wait_for_selector('a[href*="/companies/"][href*="/jobs/"]', timeout=15000)
sleep(2)
html = page.content()
jobs = _parse_page(html)
page.close()

def _parse_page(html):
    job_links = soup.select('a[href*="/companies/"][href*="/jobs/"]')

    pm_keywords = {"product manager", "product management", "senior pm", ...}
    seen = set()   # dedup by href

    for link in job_links:
        href = link["href"]
        title = link.get_text(strip=True)

        if not title or href in seen: continue
        seen.add(href)

        if not any(kw in title.lower() for kw in pm_keywords): continue

        apply_link = "https://www.ycombinator.com" + href if href.startswith("/")

        # Walk up DOM tree to find card container (up to 4 levels)
        card = link.parent
        for _ in 4:
            if card has enough job links: break
            card = card.parent

        company = ""
        location = ""
        salary = None
        posted_date = None

        if card:
            # Company from /companies/ links in card
            for cl in card.select('a[href*="/companies/"]'):
                if cl.text != title:
                    company = cl.text; break

            # Location/salary from bullet-separated card text
            parts = card.get_text(" ", strip=True).split("•")
            location_markers = ("Remote", "India", "Delhi", "Gurugram", ...)
            currency_markers = ("$", "£", "€", "₹", "CAD", "AUD", "LPA")

            for part in parts:
                if not location and any(loc in part for loc in location_markers):
                    location = part   # FIRST MATCH WINS (fixed bug — see edge_cases §4)
                    # Note: no break here — but `if not location` guards subsequent matches
                if not salary and any(curr in part for curr in currency_markers):
                    salary = part

            # Date
            date_m = re.search(r"(\d+\s*(?:day|hour|week|month)s?\s*ago|about .+? ago)", card_text, I)
            posted_date = _parse_relative_date(date_m.group(1)) if date_m

        if title and apply_link:
            if not is_acceptable_location(location):
                log debug; continue
            yield Job(platform="ycombinator", skills=[], description="YC-backed startup", ...)
```

### Schema Mapping
| Source | Target Job field | Extraction method | Notes |
|--------|-----------------|-------------------|-------|
| `a[href*="/jobs/"]` text | `title` | `link.get_text(strip=True)` | Filtered by PM keywords |
| `a[href*="/jobs/"]` href | `apply_link` | relative → absolute | `/companies/{slug}/jobs/{id}` |
| `a[href*="/companies/"]` text ≠ title | `company` | first match that isn't the job title | |
| Card text split on `•`, first location match | `location` | heuristic match on location_markers | |
| Card text split on `•`, first currency match | `salary` | heuristic match on currency symbols | |
| Card regex: `N days/hours/weeks/months ago` | `posted_date` | `_parse_relative_date()` | |

### Explicit Assumptions
- Assumes job links follow pattern `/companies/{slug}/jobs/{id}-{title-slug}`
- Assumes card text uses `•` as the delimiter between fields
- Assumes company name is found via `/companies/` links that don't match the job title
- Assumes location can be identified by a short list of location_markers in card text parts
- **Critical (fixed, §4):** First match wins for location extraction — not last match. The `if not location` guard implements this.
- Assumes `description = "YC-backed startup"` (hardcoded string, not scraped)

### Known Failure Modes
- **Fixed bug (edge case §4):** Old code set `location = part` unconditionally, so last match won. Now using `if not location` guard so first location match wins.
- Card text structure assumes `•` separators; if YC changes to comma or pipe, location/salary parsing fails silently
- DOM tree walk (`card = card.parent` up to 4 levels) may fail for deeply nested or flat HTML
- `description = "YC-backed startup"` is always a stub — no real description fetched
- Single page — no pagination. If YC moves to paginated results, only first page is captured.
- `skills = []` always

### Null/Missing Field Handling
- `title` empty → item skipped
- `href` seen before → item skipped (in-memory dedup)
- Location not found in card → `location = ""`; `is_acceptable_location("")` returns False → item filtered out
- Company not found in card → `company = ""`; job still appended
- Salary not found → `salary = None`
- Date not found → `posted_date = None`

---

## 10. Hirist (`scrapers/hirist.py`)

### Overview
- Type: Public REST JSON API (`gladiator.hirist.tech`)
- Requires Playwright: No
- Requires auth: No

### Request Construction
- Base URL: `https://gladiator.hirist.tech/job/category/`
- Query params: `page=<0-indexed>`, `categoryId=12` (Product Management), `size=20`, `industry=""`
- Auth: Referer header `https://www.hirist.tech/`
- Pagination: 0-indexed, up to `MAX_PAGES = 3` (3×20 = 60 jobs); stops on empty `data` or `hasMore == False`
- Rate limiting: `asyncio.sleep(1)` between pages

**Note:** `CATEGORY_ID = 12` (Product Management) is used instead of a text query — Hirist is category-based, not keyword-based.

**Note:** Delhi NCR filtering is done in Python via `DELHI_NCR_KEYWORDS` after fetch (not via API param).

### Pseudocode
```
CATEGORY_ID = 12         # Product Management
DELHI_NCR_KEYWORDS = {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad"}

async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
    for page_num in 0..MAX_PAGES-1:
        params = {page: page_num, categoryId: CATEGORY_ID, size: PAGE_SIZE, industry: ""}
        resp = client.get(BASE_URL + "?" + params)
        data = resp.json()

        raw_jobs = data["data"]
        if not raw_jobs: break

        for item in raw_jobs:
            title    = item["jobdesignation"] or item["title"]
            company  = item["companyData"]["companyName"]  # or str() fallback
            locations_raw = item["location"] or item["locations"] or []
            location = ", ".join(loc["name"] for loc in locations_raw)

            # Location filter — reject non-NCR
            if not any(kw in location.lower() for kw in DELHI_NCR_KEYWORDS):
                continue

            # Salary
            min_sal = item["minSal"] or 0
            max_sal = item["maxSal"] or 0
            hide_sal = item["hideSal"]
            salary = f"{min_sal} - {max_sal} LPA" if not hide_sal and (min_sal or max_sal) else None

            tags = item["tags"] or []
            skills = [t["name"] for t in tags]  # or str(t) if not dict

            apply_link = item["jobDetailUrl"] or item["applyUrl"]
            if not apply_link.startswith("http"):
                apply_link = "https://www.hirist.tech" + apply_link

            created_ms = item["createdTimeMs"] or item["createdTime"]
            posted_date = datetime.fromtimestamp(created_ms / 1000, tz=UTC).date()

            if title and company and apply_link:
                yield Job(platform="hirist", description="", ...)

        if not data["hasMore"]: break
        sleep(1)
```

### Schema Mapping
| Raw field | Target Job field | Extraction method | Type assumption |
|-----------|-----------------|-------------------|-----------------|
| `jobdesignation` or `title` | `title` | `or` fallback | string |
| `companyData.companyName` | `company` | nested dict access | dict |
| `location` or `locations` | `location` | list of `{id, name}` dicts, joined by `, ` | list of dicts |
| `minSal`, `maxSal`, `hideSal` | `salary` | formatted string or None | integers |
| `tags[].name` | `skills` | list of `{id, name, isMandatory}` | list of dicts |
| `jobDetailUrl` or `applyUrl` | `apply_link` | relative → absolute | string |
| `createdTimeMs` or `createdTime` | `posted_date` | Unix ms → UTC date | integer (ms) |

### Explicit Assumptions
- Assumes `categoryId=12` is stable and permanently maps to Product Management
- Assumes `DELHI_NCR_KEYWORDS` set is sufficient to identify all NCR locations from API response
- Assumes API location filter (`categoryId`) returns all India jobs for PM, not just NCR — Python filter is required
- Uses `is_acceptable_location()` NOT called — uses raw keyword match instead. This diverges from the location filter single-source-of-truth pattern (see guidelines §1)
- `description = ""` always

### Known Failure Modes
- `categoryId=12` may change — Hirist could reassign category IDs without notice
- **Location filter divergence:** Hirist uses its own `DELHI_NCR_KEYWORDS` set instead of `services.location_filter.is_acceptable_location()`. The two could diverge if NCR tokens are added to `location_filter.py` but not to `DELHI_NCR_KEYWORDS`. See known_edge_cases.md §1 and guidelines §1.
- Same `createdTime` / `createdTimeMs` ambiguity as IIMJobs — could be seconds not milliseconds
- `description = ""` for all jobs — no text for scoring

### Null/Missing Field Handling
- Same pattern as IIMJobs (shared parent company API structure)

---

## 11. Funding Scanner (`funding/scanner.py`)

### Overview
- Type: Multi-source HTML scraping (Inc42, YourStory, Entrackr, VCCircle) + LinkedIn cross-reference
- Requires Playwright: Yes (all four sources)
- Requires auth: No (for news sources); LinkedIn cross-reference triggers auth wall detection

### Request Construction
- Inc42: 3 URLs (`/tag/funding/`, `/tag/series-a/`, `/tag/series-b/`)
- YourStory: 1 URL (`/category/funding`)
- Entrackr: 1 URL (`/category/funding/`)
- VCCircle: 1 URL (`/deals`)
- All sources run concurrently via `asyncio.gather()`
- No pagination — scrapes the first page of each URL (20–30 articles max per source)
- Lookback filter: articles older than 180 days are skipped

### Pseudocode
```
# Run all four sources concurrently
results = await asyncio.gather(
    _scan_inc42(), _scan_yourstory(), _scan_entrackr(), _scan_vccircle(),
    return_exceptions=True
)

# Merge results, deduplicate by company name (case-insensitive)
all_companies = [c for r in results if not isinstance(r, Exception) for c in r]

seen: dict[str_lowercased_company, FundedCompany] = {}
for c in all_companies:
    key = c.company.lower().strip()
    if key not in seen:
        seen[key] = c
    else:
        # Field-by-field merge: fill blanks from new record
        for field in (founder_ceo, founder_linkedin, industry, ...):
            if not getattr(existing, field) and getattr(c, field):
                setattr(existing, field, getattr(c, field))
        # Date: prefer more recent
        if c.last_round_date > existing.last_round_date:
            existing.last_round_date = c.last_round_date

return list(seen.values())

# Per-source pattern (identical for all four):
def _scan_source():
    for url in source_urls:
        page = _get_page(url)
        html = page.content()
        articles = soup.select("article, div[class*='post-card'], ...")

        for article in articles[:20]:
            title_el = article.select_one("h2 a, h3 a, a[class*='title']")
            title = title_el.text
            link  = title_el["href"]

            # Filter: must contain funding keywords in title
            if not any(kw in title.lower() for kw in
                       ["raises", "funding", "secures", "bags", "series", "round"]):
                continue

            date_el = article.select_one("time, span[class*='date']")
            article_date = _parse_date_from_text(date_el["datetime"] or date_el.text)

            if article_date and article_date < (today - 180 days): continue

            company_name = _extract_company_from_title(title)
            amount = _extract_amount(title)
            series = _extract_series(title)

            if company_name:
                yield FundedCompany(company=company_name, ...)
        page.close()

def _extract_company_from_title(title):
    # Regex pattern: "Company Raises/Bags/Secures..."
    for pat in [r"^(.+?)\s+(?:raises?|bags?|secures?|...)\s",
                r"^(.+?)\s+(?:funding|series|round)\b"]:
        m = re.match(pat, title, IGNORECASE)
        if m:
            name = m.group(1).strip()
            # Remove common prefixes: "Startup", "Company", "Indian"
            # Remove quotes
            if len(name) > 2 and no funding-keywords in name:
                return name
    return ""

def check_linkedin_pm_roles(companies):
    for company in companies:
        url = f"https://www.linkedin.com/jobs/search/?keywords=product+manager&company={company.name}&location=India"
        company.linkedin_jobs_url = url
        page = _get_page(url)
        if "authwall" or "login" in page.url: page.close(); continue
        cards = soup.select("div.base-card, li.result-card")
        validated = count cards where PM keyword AND company word in card text
        company.linkedin_pm_roles = validated
        page.close()
        sleep(3)
```

### Schema Mapping (FundedCompany)
| Source | `FundedCompany` field | Extraction method |
|--------|----------------------|-------------------|
| Article title regex | `company` | `_extract_company_from_title()` |
| Article title regex | `amount_raised` | `_extract_amount()` — patterns: `$XM`, `₹X Cr` |
| Article title text | `last_round_series` | `_extract_series()` — keyword match in SERIES_KEYWORDS |
| `<time datetime>` or date text | `last_round_date` | `_parse_date_from_text()` — 8 format patterns |
| Article link | `source_url` | href from title element |

### Explicit Assumptions
- Assumes company name always precedes `raises/bags/secures/funding/series` in article titles
- Assumes article titles in English follow the pattern "Company Verb Amount..."
- Assumes `<time datetime>` or `<span class='date'>` elements contain the publication date
- Assumes `datetime` attribute on `<time>` element is ISO format
- Assumes 20–30 articles per page covers recent funding news
- Deduplication uses raw `company.lower().strip()` — not `_company_slug()`. This means "Acme Technologies" and "Acme Inc" are NOT deduplicated at this stage (see known_edge_cases.md §14)
- LinkedIn cross-reference: assumes partial word match of company name against card text is sufficient validation

### Known Failure Modes
- Company name extraction from title fails for non-standard headline formats (e.g., "Funding alert: Acme raises $5M")
- Dedup uses raw lowercased company name, not `_company_slug()` — "Acme Technologies Pvt Ltd" and "Acme" are treated as different companies
- Date parsing fails silently (`posted_date = None`) for non-standard date formats
- LinkedIn cross-reference: auth wall = 0 `linkedin_pm_roles`; no distinction between "0 real jobs" and "blocked"
- All four sources are scraped to first page only — recent deals may not appear if the landing page is editorial/curated
- `asyncio.gather(return_exceptions=True)` means one failed source does not block others, but its contribution is zero

### Null/Missing Field Handling
- Article without title element → skipped
- Article date absent → `article_date = None`; lookback filter skipped (all ages pass)
- Company name extraction yields `""` → article skipped
- Amount regex fails → `amount_raised = ""`
- Series keyword not found → `last_round_series = ""`

---

## 12. Apollo Outreach Client (`outreach/apollo_client.py`)

### Overview
- Type: REST API client (Apollo.io)
- Requires Playwright: No
- Requires auth: Yes (API key from `settings.APOLLO_API_KEY`)
- Two-step flow: Search (no emails) → Enrich (verified email)

### Request Construction

**Step 1: People Search**
- URL: `https://api.apollo.io/api/v1/mixed_people/api_search`
- Method: POST
- Auth: `x-api-key: {APOLLO_API_KEY}` header
- Payload: `{organization_names: [company], person_titles: [titles], per_page: 10, person_locations: [location]}`
- Default title list: `PRODUCT_TITLES` + `FOUNDER_TITLES` + `RECRUITER_TITLES`
- Returns: people list WITHOUT emails

**Step 2: People Enrich**
- URL: `https://api.apollo.io/api/v1/people/match`
- Method: POST
- Auth: `x-api-key: {APOLLO_API_KEY}` header
- Payload: `{first_name, last_name, organization_name, reveal_personal_emails: true, linkedin_url?}`
- Returns: person dict WITH `email` and `email_status`

**Rate Limiting:**
```
min_delay = 60.0 / settings.APOLLO_RATE_LIMIT_PER_MINUTE   # default: 10/min = 6s min spacing
on each call:
    elapsed = now - last_call_ts
    if elapsed < min_delay:
        sleep(min_delay - elapsed)
    last_call_ts = now
```

### Pseudocode
```
# Step 1: Search
people = search_contacts(company_name, title_keywords=None, location="India")
# people = [{id, first_name, last_name, title, organization, linkedin_url, ...}]
# NOTE: NO email in search results

# Step 2: For each person, enrich to get email
for person in people:
    enriched = enrich_person(
        first_name=person["first_name"],
        last_name=person["last_name"],
        organization_name=company_name,
        linkedin_url=person.get("linkedin_url", "")
    )
    if enriched:
        email = enriched["email"]
        email_status = enriched["email_status"]

def classify_role(title) -> "product_leader" | "founder" | "recruiter" | "other":
    if "product" or "pm " in title.lower: return "product_leader"
    if "ceo" or "founder" or "cto" in title.lower: return "founder"
    if "recruit" or "talent" or "hr" in title.lower: return "recruiter"
    return "other"
```

### Schema Mapping (Search Response)
| Apollo field | Usage | Notes |
|-------------|-------|-------|
| `people[].id` | Apollo person ID | Used as key for enrichment |
| `people[].first_name`, `last_name` | Contact name | Passed to enrich |
| `people[].title` | `contact_title` | Used for `classify_role()` |
| `people[].linkedin_url` | Passed to enrich | Improves match accuracy |
| `people[].organization` | Verification | |

### Schema Mapping (Enrich Response)
| Apollo field | Usage | Notes |
|-------------|-------|-------|
| `person.email` | `contact_email` | May be empty string |
| `person.email_status` | `contact_email_status` | `"verified"`, `"likely"`, `"invalid"`, etc. |

### Explicit Assumptions
- Assumes `APOLLO_API_KEY` is non-empty before making calls (returns `[]` / `None` if empty)
- Assumes People Search returns people without emails (Apollo pricing: search is cheap, enrich is paid)
- Assumes `reveal_personal_emails: True` in Enrich payload causes Apollo to return personal emails when corporate email unavailable
- Assumes `rate_limit > 0` for limiter to engage (handles `rate_limit = 0` gracefully — see known_edge_cases.md §13)
- `PRODUCT_TITLES`, `FOUNDER_TITLES`, `RECRUITER_TITLES` are hardcoded — changing target contact types requires code change

### Known Failure Modes
- **Fixed bug (edge case §13):** Old `request_count % rate_limit` caused ZeroDivisionError when `rate_limit=0`. Now checked before division.
- **Fixed bug (edge case §13):** Old "sleep 60 every Nth call" allowed burst. Now token-bucket per-call.
- HTTP 429 (rate limit exceeded) is caught by `httpx.HTTPStatusError` and returns `[]`/`None` — no retry
- Apollo may return person with `email: ""` and `email_status: "invalid"` — caller must check `email_status`
- No company normalization before Apollo search — `"Acme Technologies Pvt Ltd"` may not match Apollo's company data

### Null/Missing Field Handling
- `api_key` absent → returns `[]` immediately
- HTTP error → returns `[]` / `None`; logs error with status code
- `people` key absent in response → returns `[]`
- `person` key absent in enrich response → returns `None`
- Empty email in enriched person → returns person dict (caller must handle)

---

## 13. VC Portals Scraper (`vc_portals/scraper.py`)

### Overview
- Type: Multi-VC portal scraper — JSON API interception first, HTML fallback
- Requires Playwright: Yes
- Requires auth: No (uses `"vc_portals"` browser context, no login)
- Source: `VC_REGISTRY` in `vc_portals/registry.py` — iterates only VCs with `job_portal_url` set

### Request Construction
- Per VC: single page load to `vc.job_portal_url`
- Tries to type `"product manager"` into search/title input fields
- Intercepts JSON responses with keys `jobs`, `data`, `results`, `postings`, `positions`
- No pagination (single page per VC)
- Rate limiting: `asyncio.sleep(2)` between VCs
- Platform name: `f"vc_{vc.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}"`

### Pseudocode
```
vcs_with_portals = [vc for vc in VC_REGISTRY if vc.job_portal_url]

for vc in vcs_with_portals:
    jobs = _scrape_vc_portal(vc)
    sleep(2)

def _scrape_vc_portal(vc):
    captured_api = []

    def _intercept(response):
        ct = response.headers["content-type"]
        if response.status == 200 and "json" in ct:
            body = response.json()
            if isinstance(body, dict) and (
                body.get("jobs") or body.get("data") or body.get("results")
                or body.get("postings") or body.get("positions")
            ):
                captured_api.append(body)

    page = _get_page(vc.job_portal_url, intercept_fn=_intercept)
    sleep(3)

    # Try to type "product manager" into search input
    for selector in ['input[placeholder*="title"]', 'input[placeholder*="search"]', ...]:
        inp = page.query_selector(selector)
        if inp:
            inp.fill("product manager")
            sleep(3); break

    if captured_api:
        jobs = _parse_api_responses(captured_api, vc)
    if not jobs:
        html = page.content()
        jobs = _parse_html(html, vc)
    page.close()
    return jobs

def _parse_api_responses(responses, vc):
    for resp in responses:
        items = resp["jobs"] or resp["data"] or resp["results"] or resp["postings"] or resp["positions"] or []
        if isinstance(items, dict):
            items = list(items.values())

        for item in items:
            title   = item["title"] or item["name"] or item["jobTitle"]
            if not _is_pm_role(title): continue

            company = item["companyName"] or item["company"] or item["organization"] or vc.name
            loc_raw = item["locations"] or item["location"] or item["normalizedLocations"] or ""
            location = ", ".join(str(l) for l in loc_raw) if list else str(loc_raw)

            apply_link = item["applyUrl"] or item["url"] or item["hostedUrl"]
                         or item["absoluteUrl"] or item["jobUrl"]
            if relative: apply_link = urljoin(vc.job_portal_url, apply_link)

            if not (title and apply_link): continue
            if not is_acceptable_location(location): log debug; continue

            yield Job(platform=f"vc_{vc_slug}", ...)

def _parse_html(html, vc):
    # Look for job-ish links
    job_links = soup.select("a[href*='/jobs/'], a[href*='/job/'], a[href*='/careers/'], ...")

    for link in job_links:
        title = link.text
        if not _is_pm_role(title): continue
        href = link["href"]  # resolved relative

        company = vc.name  # default
        company_el = link.parent.select_one("span[class*='company'], ...")
        if company_el: company = company_el.text

        loc_el = link.parent.select_one("span[class*='location'], ...")
        location = loc_el.text if loc_el else ""

        if title and href:
            if not is_acceptable_location(location): log debug; continue
            yield Job(platform=f"vc_{vc_slug}", ...)
```

### Schema Mapping (API path — multi-key fallback)
| Tried keys (in order) | Target Job field |
|----------------------|-----------------|
| `title`, `name`, `jobTitle` | `title` |
| `companyName`, `company`, `organization`, vc.name | `company` |
| `locations`, `location`, `normalizedLocations` | `location` |
| `applyUrl`, `url`, `hostedUrl`, `absoluteUrl`, `jobUrl` | `apply_link` |

### Explicit Assumptions
- Assumes VC job portals serve JSON with one of the five key patterns (`jobs`, `data`, `results`, `postings`, `positions`)
- Assumes search inputs accept free-text "product manager" and trigger a new API response (after 3s sleep)
- Assumes all VCs with `job_portal_url` are accessible without authentication
- Assumes `company = vc.name` is an acceptable fallback when company is absent from API response
- `description = f"Via {vc.name} portfolio"` (hardcoded stub)
- `salary = None`, `skills = []` always
- `posted_date = None` always
- Platform name is dynamically generated — may not match `DIRECT_SOURCE_PLATFORMS` frozenset (see known_edge_cases.md §17)

### Known Failure Modes
- **Edge case §17:** Dynamic platform names like `vc_accel_india` are not in `DIRECT_SOURCE_PLATFORMS` frozenset. Scoring bonus for direct-source platforms is missed. Fix: check `platform.startswith("vc_")`.
- VC portals use many different ATSs (Greenhouse, Lever, Ashby, Workday, Getro) — no single HTML structure works for all
- JSON interception may capture API responses from analytics pixels, CDN calls, etc. that happen to have one of the five keys
- Search input automation: if portal requires pressing Enter or clicking a search button, just `fill()` is insufficient
- `_get_page()` in this module does NOT close the page on goto timeout (different from base `BaseScraper._get_page()` pattern) — see line 257. If `goto` times out, exception propagates but page stays open until `page.close()` in `_scrape_vc_portal()`.

### Null/Missing Field Handling
- `title` absent → item skipped
- `apply_link` absent → item skipped
- `location` absent → empty string → `is_acceptable_location("")` returns False → item filtered
- `company` absent → falls back to `vc.name`
- All other fields: None or empty string

---

## 14. MNC Careers Scraper (`mnc_careers/scraper.py`)

### Overview
- Type: Multi-MNC career page HTML scraping (SPA/SSR mixed)
- Requires Playwright: Yes
- Requires auth: No
- Source: `MNC_REGISTRY` — iterates only MNCs with `pm_search_url` set
- Processed in batches of 5 via `asyncio.gather()`

### Request Construction
- Per MNC: single page load to `mnc.pm_search_url` (pre-built search URL per MNC)
- Waits for job-ish selector or falls through after 12s timeout
- No pagination (single page per MNC)
- Rate limiting: `asyncio.sleep(3)` between batches (5 MNCs per batch)
- Platform name: `f"mnc_{mnc.name.lower().replace(' ', '_').replace('/', '_')}"`

### Pseudocode
```
mncs_with_urls = [m for m in MNC_REGISTRY if m.pm_search_url]

# Batch of 5, with 3s sleep between batches
for i in 0..len(mncs)..5:
    batch = mncs[i:i+5]
    results = await asyncio.gather(*[_scrape_mnc(m) for m in batch], return_exceptions=True)
    sleep(3)

def _scrape_mnc(mnc):
    page = _get_page(mnc.pm_search_url)   # closes page on goto failure, re-raises
    sleep(3)

    page.wait_for_selector(
        "div[class*='job'], a[class*='job'], li[class*='job'], div[class*='position'], ...",
        timeout=12000
    )

    html = page.content()

    listings = soup.select("div[class*='job-result'], div[class*='job-card']")
              or soup.select("a[class*='job'], a[class*='position']")
              or soup.select("li[class*='job'], li[class*='result']")
              or soup.select("tr[class*='job'], div[class*='posting']")
              or soup.select("div[class*='card'], div[class*='listing']")
              or soup.select("article")

    for el in listings:
        text = el.get_text(" ", strip=True).lower()
        if not any(kw in text for kw in PM_KEYWORDS): continue

        title_el = el.select_one("h2, h3, h4, a[class*='title'], span[class*='title'], div[class*='title']")
        title = title_el.text if title_el else ""

        link_el = el.select_one("a[href]") or (el if el.name=="a" else None)
        href = link_el["href"]
        if relative: href = urljoin(mnc.pm_search_url, href)

        # CRITICAL: NO FALLBACK to mnc.delhi_ncr_office (fixed bug — see edge_cases §11)
        loc_el = el.select_one("span[class*='location'], div[class*='location'], ...")
        location = loc_el.text if loc_el else ""

        if not (title and href): continue
        if not is_acceptable_location(location): log debug; continue

        yield Job(platform=f"mnc_{mnc_slug}", company=mnc.name, description=f"Direct from {mnc.name} careers page", ...)
    page.close()
```

### Schema Mapping
| CSS selector | Target Job field | Notes |
|--------------|-----------------|-------|
| `h2, h3, h4, a[class*='title']...` | `title` | Multiple fallbacks |
| `a[href]` | `apply_link` | Relative resolved via `urljoin` |
| `span[class*='location']...` | `location` | NO fallback if absent |
| (always) `mnc.name` | `company` | Hardcoded from registry — not extracted from HTML |

### Explicit Assumptions
- Assumes MNC career pages render job listings on the first page (no scroll needed)
- Assumes PM keyword match in full card text (`el.get_text()`) is sufficient to identify PM roles
- Assumes `title` element is within the listing element
- Assumes location element uses class names containing "location" or "loc"
- `company = mnc.name` always (from registry, not HTML) — correct assumption for dedicated career pages
- `description = "Direct from {mnc.name} careers page"` (stub)
- `salary = None`, `skills = []`, `posted_date = None` always

### Known Failure Modes
- **Fixed bug (edge case §11):** Old code fell back to `mnc.delhi_ncr_office` when location element was absent. Now uses empty string → `is_acceptable_location("")` returns False → item filtered. No ghost "Gurugram" jobs.
- **Edge case §17:** Dynamic platform names `mnc_{name}` not in `DIRECT_SOURCE_PLATFORMS`. Scoring bonus missed. Fix: check `platform.startswith("mnc_")`.
- MNC career pages use diverse ATSs (Taleo, Workday, Greenhouse, custom); no single HTML structure works reliably
- Workday/Taleo SPAs may require interaction (pagination, "load more") before all jobs appear
- 12-second `wait_for_selector` timeout may be insufficient for slow-loading SPAs
- `asyncio.gather()` batching: if 3 of 5 in a batch fail, the other 2 still complete — good isolation
- `_get_page()` in this module DOES close the page on goto failure (unlike vc_portals — see line 152: `await page.close(); raise`)

### Null/Missing Field Handling
- `title` absent → empty → item skipped
- `href` absent → empty → item skipped
- `location` element absent → `location = ""`; `is_acceptable_location("")` returns False → item filtered
- `company` always `mnc.name` (from registry)
- All other fields: None or empty string

---

## 15. Storage Layer (`storage/db.py`)

### Overview
- Single SQLite file: `output/jobs.db`
- Tables: `jobs`, `runs`, `company_profiles`, `applications`, `network_contacts`, `job_connection_matches`
- Schema migrations are idempotent: `ALTER TABLE ... ADD COLUMN` is skipped if column exists

### Key Patterns

**Dedup flow:**
```
insert_job(job):
    if job_exists(job.id): return False   # exact platform+company+title+link duplicate
    INSERT into jobs with dedup_hash
    return True

# Cross-platform dedup (runs after all scrapers complete):
get_jobs_by_dedup_hash(hash) → returns all jobs with same normalized company+title+region
mark_duplicate(job_id, duplicate_of=first_seen_id)
```

**Scoring sentinel:**
```
get_jobs_for_scoring(rescore_all=False):
    if rescore_all:
        SELECT * WHERE is_duplicate = 0
    else:
        SELECT * WHERE is_duplicate = 0 AND priority_bucket = ''
    # NOTE: not priority_score = 0 — see known_edge_cases.md §8
```

**Application upsert:**
```
upsert_application():
    ON CONFLICT(id) DO UPDATE SET
        applied_at = COALESCE(excluded.applied_at, applications.applied_at)
        # See known_edge_cases.md §9 — prevents wiping existing timestamps
```

**Warmth score updates:**
```
update_job_warmth_score(job_id, warmth):
    UPDATE jobs SET warmth_score = ? WHERE id = ?
    # NO COMMIT — caller must commit after batch
    # See CLAUDE.md: "update_job_warmth_score does NOT commit"
```

### Key Schemas

**`jobs` table:**
- `id` TEXT PRIMARY KEY (16-char SHA256)
- `dedup_hash` TEXT (indexed)
- `priority_bucket` TEXT DEFAULT '' (empty = "never scored" sentinel)
- `priority_score`, `relevance_score`, etc. INTEGER DEFAULT 0

**`applications` table:**
- `status` TEXT — must be from `APPLICATION_STATUSES` frozenset
- `applied_at` TEXT — preserved via COALESCE in upsert
- Application ID generated by `application_id_for(job_id)` — not `f"app_{job_id}"`

### Explicit Assumptions
- Assumes `output/` directory can be created at runtime
- Assumes SQLite single-writer, no concurrent writes from multiple processes
- `_row_to_dict()` parses `skills` JSON on every read — assumes `skills` column is always valid JSON
- `APPLICATION_STATUSES` frozenset is the canonical vocabulary — both CLI and API import from here

### Known Failure Modes
- See known_edge_cases.md §8: `priority_bucket = ''` sentinel vs `priority_score = 0`
- See known_edge_cases.md §9: status vocabulary drift (fixed), `applied_at` wipe (fixed via COALESCE), dual app ID schemes (fixed)
- See known_edge_cases.md §10: duplicate application rows produce nondeterministic join results if not ordered by `last_action_at DESC`
- `update_job_warmth_score()` does not commit — calling code must batch and commit explicitly

---

## Cross-Cutting Concerns

### Location Filter as Single Source of Truth

All scrapers that apply per-job location filtering call `services.location_filter.is_acceptable_location()`. Notable exception: **Hirist** uses its own `DELHI_NCR_KEYWORDS` set instead — a potential drift point.

Scrapers that do NOT apply location filters (potential gap):
- **LinkedIn** — location param is unreliable; no per-job filter applied
- **Wellfound** — location param unreliable; no per-job filter applied
- **Indeed** — location param unreliable; no per-job filter applied
- **IIMJobs** — relies on `loc=1` API param; no per-job filter
- **Instahyre** — relies on `jobLocations="Delhi / NCR"` API param; no per-job filter

Scrapers that DO apply per-job `is_acceptable_location()`:
- RemoteOK, YCombinator, VC Portals, MNC Careers, Funding Scanner (LinkedIn check)

### Description Fetch Patterns

| Scraper | Description Strategy | Resource Leak Risk |
|---------|---------------------|-------------------|
| RemoteOK | Inline in API response; HTML stripped | None |
| Naukri (API path) | `jobDescription` field inline | None |
| Naukri (HTML path) | Separate page load per card | try/finally with `page=None` sentinel |
| IIMJobs | Always `""` | None |
| LinkedIn | Separate page load (up to 10) | try/finally with `page=None` sentinel |
| Wellfound | Separate page load per card | try/finally with `page=None` sentinel |
| Indeed | Separate page load per card | try/finally with `page=None` sentinel |
| Instahyre | Always `""` | None |
| YCombinator | Always `"YC-backed startup"` | None |
| Hirist | Always `""` | None |
| VC Portals | Always `"Via {vc.name} portfolio"` | None |
| MNC Careers | Always `"Direct from {mnc.name} careers page"` | None |

### Platform Name Conventions

| Scraper | Platform value | Dynamic? |
|---------|---------------|----------|
| RemoteOK | `"remoteok"` | No |
| Naukri | `"naukri"` | No |
| IIMJobs | `"iimjobs"` | No |
| LinkedIn | `"linkedin"` | No |
| Wellfound | `"wellfound"` | No |
| Indeed | `"indeed"` | No |
| Instahyre | `"instahyre"` | No |
| YCombinator | `"ycombinator"` | No |
| Hirist | `"hirist"` | No |
| VC Portals | `f"vc_{vc.name.lower()...}"` | Yes — see edge_cases §17 |
| MNC Careers | `f"mnc_{mnc.name.lower()...}"` | Yes — see edge_cases §17 |

**Important:** Dynamic platform names `vc_*` and `mnc_*` are not in `DIRECT_SOURCE_PLATFORMS` frozenset in `services/scoring.py`. The scoring bonus for direct sources requires `platform.startswith("vc_") or platform.startswith("mnc_")` check.

### SearchParams Usage

| Scraper | Uses `search_params.title_keywords[0]`? | Notes |
|---------|----------------------------------------|-------|
| Naukri | Yes | Used in URL construction |
| IIMJobs | Yes (with fallback `"product manager"`) | `getattr` fallback |
| LinkedIn | Yes | Used in URL keyword |
| Indeed | Yes | Used in `q=` param |
| Instahyre | Yes (with fallback `"product management"`) | `getattr` fallback |
| RemoteOK | No | Hardcoded pm_keywords set |
| Wellfound | No | Hardcoded URL `?role=product-manager` |
| YCombinator | No | Hardcoded URL `/role/product-manager` |
| Hirist | No | Hardcoded `categoryId=12` |

Scrapers that don't use `search_params.title_keywords[0]` will silently ignore changes to the search configuration (see known_edge_cases.md §7).
