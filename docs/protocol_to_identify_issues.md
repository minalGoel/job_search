# Protocol to Identify Issues

> **Purpose:** Repeatable, deterministic process for auditing a class of bug (resource leaks, data validation, silent error swallowing, etc.) across the codebase. Follow this protocol **before writing fixes**, not after.
>
> **When to use:**
> - User reports "the data looks wrong" or "this feels off"
> - You suspect a pattern that might exist in multiple files
> - After a sub-agent returns an audit report (to verify it)
> - Before any large refactor that touches crosscutting concerns

---

## Phase 0 — Frame the hypothesis

Before reading any code, write down (in a scratchpad, chat, or `TodoWrite`):

1. **What is the symptom?** ("Expedia jobs stamped Gurugram but they're all in UK/US")
2. **What layer could cause it?** (scraper parsing? search URL? post-process filter? DB dedup? UI filter?)
3. **What is the minimum change that would confirm or refute the hypothesis?** (read the specific line the agent named; run the new filter against the existing DB)

Skipping Phase 0 leads to chasing the wrong file for 20 minutes.

---

## Phase 1 — Cast a wide net with parallel search

Use `Grep` + `Glob` in parallel (single tool-use block, multiple calls) to find every occurrence of the pattern. Key templates:

### Resource leak hunt
```
Grep pattern: "new_page\(\)|_get_page\("     type: py
Grep pattern: "page\.close\(\)"               type: py
Grep pattern: "db\s*=\s*_jobs_db\(\)"         type: py
Grep pattern: "db\.close\(\)"                 type: py
Grep pattern: "raise HTTPException"           type: py
```
Then compare counts: if you have 30 `new_page()` calls and 25 `page.close()` calls, there's a 5-page leak somewhere.

### Hardcoded strings that should be config
```
Grep pattern: '"product manager"|"Delhi / NCR"|"Delhi NCR"'  type: py
Grep pattern: 'search_params\.title_keywords'                 type: py
```
Scrapers that don't import `search_params` are ignoring user config.

### Silent error swallowing
```
Grep pattern: "except Exception"             type: py
Grep pattern: "return \[\]"                   type: py
Grep pattern: "pass$"                         type: py
```
Cross-reference: any `except Exception:` followed by `return []` or `pass` is a candidate.

### Status vocabulary drift
```
Grep pattern: '"applied"|"shortlisted"|"interviewing"|"screening"|"interview"'  type: py
```

### Hash / dedup key hunt
```
Grep pattern: "hashlib\.sha256|dedup_hash"    type: py
```

---

## Phase 2 — Verify personally before trusting a sub-agent

Sub-agents are great for coverage but can hallucinate line numbers or miss edge cases. Before touching code:

1. **Pick the top 3 most severe findings** from the sub-agent report
2. Read the actual file/line with the `Read` tool
3. Quote the exact code back to yourself
4. Check: does the line actually do what the agent claimed?

**Example:** during the location-filter audit, a sub-agent reported that `vc_portals/scraper.py` had "no location filter at all." Reading lines 140–180 confirmed it — but also revealed that the file **declared** `LOCATION_KEYWORDS` on line 25 and **never used it**. That's a second bug the agent missed.

---

## Phase 3 — Run the filter/check against existing data

The single most valuable audit step: run your proposed fix as a **read-only query** against the existing DB first. This tells you:

- Whether the fix agrees with historical expectations (if it rejects 95%, something's wrong)
- Which platforms are the worst offenders
- Whether there are hidden data-quality issues unrelated to the current bug

### Template
```python
source .venv/bin/activate && python -c "
import sqlite3
from collections import Counter
from services.X import new_filter_fn  # the proposed fix

conn = sqlite3.connect('output/jobs.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT platform, location, company, title FROM jobs WHERE is_duplicate = 0').fetchall()

accepted = rejected = 0
by_platform = Counter()
samples = []
for r in rows:
    if new_filter_fn(r['location'] or ''):
        accepted += 1
    else:
        rejected += 1
        by_platform[r['platform']] += 1
        if len(samples) < 20:
            samples.append((r['platform'], r['company'], r['title'][:50], r['location'][:40]))

print(f'Accepted: {accepted}, Rejected: {rejected} ({rejected/len(rows)*100:.1f}%)')
for p, c in by_platform.most_common(10):
    print(f'  {p}: {c}')
print('\nSample rejected rows:')
for s in samples: print(f'  {s}')
"
```

This is the step that caught both the Expedia field-fallback bug AND the Naukri placeholder field-mapping bug on the same audit run. The Naukri bug wasn't in the original hypothesis — it surfaced because the rejected-rows sample showed `location='4-6 Yrs'` repeatedly.

---

## Phase 4 — Categorise every finding by severity and blast radius

For each bug, answer:

| Dimension | Options |
|---|---|
| **Severity** | Critical (wrong data enters DB) · High (crash / silent failure) · Medium (wrong behaviour in edge cases) · Low (cosmetic) |
| **Blast radius** | One file · One module · Crosscutting (touches many files) |
| **Reversibility** | Can be fixed by re-running (idempotent) · Requires data migration · Destructive |
| **Discovery source** | User report · Sub-agent · Personal read · Data audit |

Critical + crosscutting + data-migration-required gets the highest priority. Fix these first.

---

## Phase 5 — Write fixes with explicit defence in depth

For each bug class (not individual bug), think "if this check fails, what catches it next?"

- **Data validation:** scraper-level + pipeline-level + (optional) API-level filters
- **Resource cleanup:** scope-level `finally` + `__del__` / context managers + outer orchestrator timeouts
- **Rate limiting:** client-side delay + server-side retry with exponential backoff
- **Error propagation:** `_safe_scrape` returns error string + `runs.errors` column records it + monitor parses the column

One layer is a bug waiting to happen. Two layers is fault tolerance.

---

## Phase 6 — Three-layer verification

Before declaring the fix done, run **all three** layers. If any layer is skipped, the fix isn't done.

### Layer 1: Compile check
```bash
source .venv/bin/activate && python -c "
import importlib
modules = ['services.location_filter', 'models.job', 'api.server', 'main', ...]
for m in modules:
    importlib.import_module(m)
print('✓ All modules compile')
"
```
**Cheapest, fastest. Never skip.**

### Layer 2: Behavioral smoke test
Write a short Python script that exercises the specific fix with mock data:
```python
# Bug 11: applied_at preservation
db.upsert_application({..., "applied_at": "2026-04-01", ...})
db.upsert_application({..., "applied_at": None, "status": "interview", ...})
row = db.conn.execute("SELECT applied_at FROM applications WHERE id = ?", (aid,)).fetchone()
assert row[0] == "2026-04-01", f"REGRESSION: applied_at erased, got {row[0]}"
```
This is where "the code compiles but the SQL is still wrong" gets caught.

### Layer 3: E2E runtime
Start the server / run the scraper for real with one platform. Hit the endpoint with `curl`. Check the logs.
```bash
python main.py serve --port 8000 &
sleep 3
curl -s -X POST -d '{"status":"interviewing"}' http://localhost:8000/api/jobs/nonexistent/status
# → should show canonical status set, not legacy set
```
This catches stale server processes, import ordering, and middleware config issues that static checks miss.

---

## Phase 7 — Document the finding

For every non-trivial bug that made it to `main`, add an entry to:
- **`docs/known_edge_cases.md`** — the specific data shape / API behaviour that broke the naive implementation
- **`docs/guidelines_and_learnings.md`** — the generalisable principle (only if this is the Nth instance of the same class)

Include:
- File path + line number of the fix (so future sessions can pattern-match)
- A minimal reproducer test case
- The pattern someone should grep for when adding similar code

---

## Common audit recipes

### Recipe A — "Data looks wrong in the dashboard"

1. Pick one bad row. Read its `platform`, `company`, `title`, `location`.
2. Identify which scraper produced it (`platform` field).
3. Read that scraper's extraction code with line numbers.
4. Hypothesise: is the field mapping wrong, or is the upstream data wrong?
5. Confirm by reading the scraper's live API/HTML response for that specific job (`curl`, browser devtools).
6. Apply Phase 3 audit to see how many other rows have the same problem.

### Recipe B — "Too many page/connection leaks"

1. Grep for `new_page`, `_get_page`, `db = _jobs_db()` — count them.
2. Grep for `page.close`, `db.close()` — count those.
3. Any mismatch is a candidate leak.
4. For each candidate, read the function and check: is every `return` / `raise` path preceded by a close?
5. Fix with `try/finally + sentinel` pattern (see `guidelines_and_learnings.md §4`).

### Recipe C — "Silently wrong counts / stats"

1. Grep for `except Exception` followed by `pass` or `return []`.
2. Read each occurrence — is it a legitimate "best effort" fallback, or hiding a real error?
3. Add logging at minimum; change to error propagation where appropriate.

### Recipe D — "Same thing defined in two places"

1. Pick a canonical name (e.g., `APPLICATION_STATUSES`).
2. Grep for the string (status values, enum members, allowlist items).
3. Every hit is a candidate duplicate. Extract to a single canonical module, import everywhere.
4. Delete the duplicates.
5. Compile-check to catch missed imports.

---

## Anti-patterns (stop and rethink)

- **"I'll just add a quick check here"** — you're creating a drift risk. Extract to a shared helper first.
- **"Let me trust the sub-agent and start fixing"** — verify the top 3 findings yourself first (Phase 2).
- **"The fix compiles so I'm done"** — run Layer 2 (behavioural) and Layer 3 (E2E) before claiming done.
- **"The rejection count looks high, I'll loosen the filter"** — audit the rejected rows first. The filter might be right; the data might be polluted.
- **"I'll fix this file and move on"** — grep for the pattern. If it exists once, it probably exists elsewhere (Phase 1).
- **"The docs say X, so X is true"** — cross-check against the code. Doc–code drift is a common bug source.
