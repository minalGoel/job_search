# Guidelines & Learnings

> **Purpose:** Codified principles for writing code in this repo. These are derived from bugs that actually shipped — every rule below exists because its absence caused an incident.
>
> **When to update:** After fixing a class of bug (not just a single instance), extract the generalisable principle here.

---

## 1. Single source of truth or it will diverge

Whenever the same concept appears in two places, one will silently drift from the other. In this codebase the pattern is: **define once in a canonical module, import everywhere.**

| Concept | Canonical home | Used by |
|---|---|---|
| Location validation | `services/location_filter.py` | every scraper, `main.py` pipeline gate, `api/server.py` |
| Company slug normalisation | `services/scoring._company_slug()` | scorer, outreach dedup, company profile lookups |
| Application status vocabulary | `storage/db.APPLICATION_STATUSES` | CLI `apply-status`, API `/jobs/:id/status`, `/applications/:id/status` |
| Application ID generation | `storage/db.application_id_for()` | CLI `shortlist`, API `shortlist_job`, `update_job_status` |
| "Counts as applied" statuses | `storage/db.STATUSES_COUNTING_AS_APPLIED` | API status updates, `/api/today` follow-up detector |

**Rule:** If you catch yourself writing the same allowlist, normalizer, or enum in a second file, stop and extract it first.

---

## 2. Never trust external data — validate every field, every row

The codebase ingests from ~20 different sources (job boards, VC portals, MNC careers, RSS feeds, APIs). Every one of them will, at some point:

- Return data in a format that worked yesterday but doesn't today
- Lie about their filters (search URL says India, results are global)
- Include regional restrictions buried in description bodies
- Emit empty fields where previously they were populated
- Change their JSON schema without versioning

**Rules:**
- Validate the field you care about on **every row**, not once per page
- Reject rows whose critical fields are empty — don't fall back to a "sensible default" (that's Bug #11 in `known_edge_cases.md`)
- Log rejection reasons with enough context to debug later (`reason=explain_location(loc)`)
- Keep a per-platform "rejected count" in the run log so you can spot regressions ("wait, why is Naukri now rejecting 80%?")

---

## 3. Defense in depth for ingestion filters

One filter is one bug away from disabled. Prefer two filters in series:

```
scraper-level filter  →  pipeline-level gate  →  database
```

- **Scraper-level** filter catches issues early and reduces pipeline work
- **Pipeline-level** gate in `main.py _run_all()` is the safety net that catches anything that slipped through (new scrapers, refactors, etc.)
- Both call the **same** `is_acceptable_location()` function so there's no drift

---

## 4. Resource management: `try/finally` with a sentinel, always

Any code that opens a Playwright page, SQLite connection, file handle, or network socket must release it on **every** exit path, including exceptions. The pattern:

```python
page = None
db = None
try:
    page = await ctx.new_page()
    db = _jobs_db()
    # ... work ...
    return result
except Exception:
    log.exception("context.failed")
    return fallback
finally:
    if page is not None:
        try:
            await page.close()
        except Exception:
            pass
    if db is not None:
        db.close()
```

**Why the sentinel:** initialising `page = None` before the `try` means the `finally` block works even if `new_page()` itself raises.

**Why the nested try in finally:** `close()` on an already-broken resource can throw. Swallow it.

**Why not context managers:** Playwright pages and `JobDB` don't implement `__aenter__/__aexit__`. Wrap them yourself if you want `async with`.

**Every FastAPI endpoint** that opens a DB must either use this pattern or a FastAPI `Depends()` generator — not leave `db.close()` sitting at the end of the happy path.

---

## 5. `_safe_scrape` must not swallow exceptions

Returning `[]` on exception is worse than returning nothing — downstream assumes a successful scrape with zero results and the error gets dropped on the floor. The correct return shape is:
```python
async def _safe_scrape(self) -> tuple[list[Job], str | None]:
    try:
        return await self.scrape(), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
```

The orchestrator then records the error in the `runs` table so we actually know what broke.

---

## 6. Centralize validation logic; reject in exactly one place

Don't scatter `if loc in NCR_TOKENS:` checks across 14 scrapers. Don't write `if status in {"applied", "interview", ...}:` in every endpoint. Define the allowlist once, import it, and validate at the boundary.

**Why:** adding a new NCR token (say "Faridabad" is in scope now) should be a one-line change, not a 14-file sweep.

---

## 7. `COALESCE` instead of `=` for partial updates

SQL upsert patterns that blindly overwrite every column destroy data. For any column that is "set once, don't overwrite later", use:
```sql
column = COALESCE(excluded.column, table.column)
```
so that sending `NULL` from the caller preserves the existing value instead of wiping it. See `storage/db.upsert_application` — `applied_at`, `notes`, `resume_version`, `cover_letter_path` all use this pattern.

---

## 8. Deterministic joins when you expect duplicates

If a table has or ever had duplicate rows per foreign key (applications, contacts, etc.), dict-based joins pick **whichever row iteration order gave you last**. That's not a bug you can fix in the consumer — it's a bug in the join. Add an `ORDER BY last_action_at DESC` (or similar "latest wins" clause) and take the first row per key.

---

## 9. Rate limiting: use token-bucket, never "sleep every Nth call"

The `if request_count % N == 0: sleep(60)` pattern fails two ways:
1. Divides by N — crashes on `N = 0` (disabled)
2. Lets N calls burst instantaneously before the pause

Use **minimum delay between consecutive calls** (`min_delay = 60.0 / rate_per_min`), tracking `last_call_ts`. This spreads load evenly and can't violate the limit. See `outreach/apollo_client._rate_limit()`.

---

## 10. Log with enough context to reproduce

Every warning/error log line should include the key identifiers someone would need to reconstruct what happened:

```python
# bad
self._log.debug("description.fetch_failed")

# good
self._log.debug("description.fetch_failed", url=url, selector=sel)
```

```python
# bad
log.warning("pipeline.location_rejected")

# good
log.debug("pipeline.location_rejected",
          platform=name, title=job.title, company=job.company,
          location=job.location, reason=explain_location(job.location))
```

---

## 11. Documentation–code drift is a bug class

When `CLAUDE.md` or docstrings say "this function strips legal suffixes" and the code doesn't, **the code is wrong, not the docs.** Treat doc–code drift as a signal to investigate: either the doc is stale (update it) or the code regressed (fix it). Always run the protocol in `protocol_to_identify_issues.md` when you spot a gap.

---

## 12. Scraping: per-job validation > search URL filters

Portal search URLs (`?location=delhi`, `?q=product+manager`) are **hints** to the portal's ranker, not contracts. Every scraper must:
1. Pull the configured query from `self.search_params.title_keywords[0]` (never hardcode)
2. Fetch results pessimistically (assume the filter was ignored)
3. Validate every result's `location`, `title`, `company` against the configured allowlist
4. Reject with a reason log, don't default

---

## 13. Dedup keys must encode every dimension you care about

If you want to dedup across platforms **within the same location**, include normalised location in the hash. If you want to dedup across roles at the same company, include title. The general rule: **the hash must contain every field you'd accept as "these are actually the same job."**

Expedia London and Expedia Delhi are **not** the same job. That means `dedup_hash` must include region.

---

## 14. Audit existing data when changing a filter

When you tighten a filter, don't just deploy it — run the new filter against the existing DB first and report how many rows would be rejected. If the number is > 30%, something is wrong with either your filter or your data; investigate before purging.

**Script pattern:**
```python
rows = db.conn.execute("SELECT platform, location, company, title FROM jobs").fetchall()
rejected = [r for r in rows if not is_acceptable_location(r["location"] or "")]
print(f"Would reject {len(rejected)}/{len(rows)} ({len(rejected)/len(rows)*100:.1f}%)")
# print breakdown by platform, sample rows
```

---

## 15. Parallelise reads, serialise writes

When auditing or exploring, dispatch multiple Read/Grep/Glob calls in a single tool-use block to cut latency. When editing, serialise per-file so edits don't stomp each other. Use `TodoWrite` to keep track of which files are in-flight.

---

## 16. Verify sub-agent findings before acting on them

Sub-agents (Explore, general-purpose) are excellent for covering a lot of ground fast, but they can hallucinate line numbers, miss edge cases, or misread code. **Always re-read the top 2–3 "critical" findings yourself** with the Read tool and quote the exact code before making fixes based on them.

The audit that kicked off this repo's biggest bug fix started with a sub-agent report; personally verifying the three claims it rated "critical" is what caught a Naukri placeholder field-mapping bug the sub-agent had not found.

---

## 17. When fixing a bug, fix the class of bug

If one scraper leaks pages on exception, the other 13 probably do too. If one endpoint forgets `db.close()` on the 404 path, check every endpoint. Don't declare victory after a single fix — grep for the pattern across the codebase.

---

## 18. Frontend: design tokens in one place, mirrored in JS

The dashboard (`static/index.html`) applies the same single-source-of-truth principle as the backend:

- **CSS `:root`** is the sole definition point for every color — page surfaces, text hierarchy, accent, semantic palette, sidebar tokens (`--sb-*`), and log console tokens (`--log-*`). No hex values appear in CSS rules or HTML inline styles outside this block.
- **`const DS`** at the top of the `<script>` block mirrors every token used by render functions. JS logic references `DS.grn`, `DS.amb`, `DS.acc`, etc. — never raw hex strings.

**Why this matters:** The sidebar was hardcoded with dark hex values (`#0E1219`, `#C8D6E5`, `#3A4E62`). A full light-mode redesign updated every other surface but the sidebar stayed dark, because its colors were invisible to the theme refactor. The bug was caused by ~40 scattered hex values across CSS, HTML, and JS that shared no common ancestry.

**Rule:** Adding a color anywhere in the file is a two-edit operation:
1. Define the token in `:root` (CSS) and `DS` (JS)
2. Reference it by name everywhere else

If you find a raw hex value outside `:root` / `DS`, treat it as a bug of the same class as an inline location allowlist in a scraper — extract it first.

---

## 19. ML model loading: lazy singleton + threading.Lock + graceful degradation

Any module that loads a heavy model (sentence-transformers, transformers, etc.) must follow three rules:

**1. Lazy singleton with a `threading.Lock`:**
```python
_lock = threading.Lock()
_model = None

def _load():
    global _model
    if _model is not None:          # fast path — no lock
        return _model
    with _lock:
        if _model is not None:      # re-check inside lock
            return _model
        _model = load_heavy_thing()
        return _model
```
Double-checked locking prevents two threads from loading simultaneously while avoiding lock acquisition on every call after warm-up.

**2. Graceful degradation on `ImportError`:**
```python
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    log.warning("package not installed")
    return None, None   # callers treat None as score = 0
```
Optional ML deps must never crash the pipeline. The feature silently contributes 0 instead.

**3. Candidate text from config, not hardcoded:**
The embedding anchor (what "good" looks like) is built from `data/candidate_profile.json`, not from a literal string. If the candidate profile changes, rescoring automatically reflects the new profile without code changes.

See `services/semantic_scorer.py` for the reference implementation.

---

## 20. Tests in three layers

1. **Compile check** — every touched module imports cleanly. Cheapest, fastest, most reliable.
2. **Behavioral smoke test** — one Python inline script that imports the changed functions and asserts the specific behaviour you claim to have fixed. This is where you catch "the fix compiled but doesn't actually fix the bug."
3. **E2E runtime test** — start the server, hit the endpoint with `curl`, check the response. This is where you catch middleware ordering, async shadowing, and port/process-lifecycle issues.

Always run all three layers before declaring a fix done.
