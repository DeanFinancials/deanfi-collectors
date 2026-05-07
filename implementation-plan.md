# Pipeline Reliability Implementation Plan

**Goal:** Make data available to deanfi-website more consistently by ensuring partial
collector success always produces a commit, eliminating silent DST-related schedule
drift, adding per-workflow timeouts to prevent queue starvation, and surfacing
data freshness to the website.

**Staleness tolerance agreed:** 1 hour for high-frequency (10-min) data; 24 hours
for nightly data. A partial update is always better than no update.

---

## Phase 1 — `market-data-10min.yml` (highest priority)

This workflow runs ~48×/day. One transient yfinance failure currently aborts the
entire run and nothing gets committed.

### 1.1 — Replace dual EST/EDT crons with one year-round schedule

**Current:**
```yaml
- cron: '5-55/10 13-16 * * 1-5'  # Morning session EST
- cron: '5-55/10 18-21 * * 1-5'  # Afternoon session EST
# - cron: '5-55/10 12-15 * * 1-5'  # Morning session EDT (commented out)
# - cron: '5-55/10 17-20 * * 1-5'  # Afternoon session EDT (commented out)
```

**Replace with:**
```yaml
- cron: '5-55/10 12-21 * * 1-5'  # 8am-5pm ET year-round (market-hours guard handles DST)
```

- [x] Replace the four cron lines (two active, two commented) with the single line above
- [x] Delete the EDT comment block — the guard in step 1.2 makes it obsolete

### 1.2 — Add market-hours guard step

Add this as the **first step after "Install dependencies"**, before any data
collection. It sets a `GITHUB_OUTPUT` variable that gates all collection steps.

```yaml
- name: Check market hours
  id: hours_check
  run: |
    python3 << 'EOF'
    from datetime import datetime
    import zoneinfo, os
    et = datetime.now(zoneinfo.ZoneInfo('America/New_York'))
    in_hours = 8 <= et.hour < 17
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'in_market_hours={str(in_hours).lower()}\n')
    status = "OPEN" if in_hours else "CLOSED"
    print(f"Market {status} — ET time: {et.strftime('%H:%M %Z')}")
    EOF
```

- [x] Add the step above immediately after "Install dependencies"

### 1.3 — Add job-level timeout

```yaml
jobs:
  fetch-and-publish:
    runs-on: ubuntu-latest
    timeout-minutes: 10          # ← add this line
```

- [x] Add `timeout-minutes: 10` to the `fetch-and-publish` job

### 1.3b — No in-script retry logic needed

The workflow still runs every 10 minutes. The next scheduled run is the retry.
With a 1-hour staleness tolerance and `continue-on-error` isolation in place,
6 consecutive runs would have to fail before users see stale data. No changes
to Python scripts are needed for retry handling.

### 1.4 — Isolate all collection steps

Add `continue-on-error: true` and the market-hours condition to every collection
step. Pattern to apply:

```yaml
- name: Fetch daily breadth          # existing name
  continue-on-error: true            # ← add
  if: steps.hours_check.outputs.in_market_hours == 'true'   # ← add
  run: |
    ...existing run block...
```

Apply to these steps (exact names from the file):

- [x] `Fetch daily breadth`
- [x] `Fetch A/D line historical`
- [x] `Fetch MA percentage historical`
- [x] `Fetch highs/lows historical`
- [x] `Fetch volume metrics historical`
- [x] `Fetch all index data`
- [x] `Fetch Price vs MA data`
- [x] `Fetch MA Spreads data`
- [x] `Fetch implied volatility data` (already has `|| echo` fallbacks; also add `continue-on-error: true` and the `if` condition for consistency)

### 1.5 — Make the copy step resilient

**Current copy step** fails if any output file is missing (e.g., a script failed
and didn't produce its `.json`). Add `2>/dev/null || true` to every `cp` line.

```yaml
- name: Copy all files to data repo
  if: steps.hours_check.outputs.in_market_hours == 'true'
  run: |
    mkdir -p data-cache/advance-decline
    cp advancedecline/daily_breadth.json data-cache/advance-decline/ 2>/dev/null || true
    cp advancedecline/ad_line_historical.json data-cache/advance-decline/ 2>/dev/null || true
    cp advancedecline/ma_percentage_historical.json data-cache/advance-decline/ 2>/dev/null || true
    cp advancedecline/highs_lows_historical.json data-cache/advance-decline/ 2>/dev/null || true
    cp advancedecline/volume_metrics_historical.json data-cache/advance-decline/ 2>/dev/null || true

    mkdir -p data-cache/major-indexes
    cp majorindexes/*.json data-cache/major-indexes/ 2>/dev/null || true

    mkdir -p data-cache/meanreversion
    cp meanreversion/*.json data-cache/meanreversion/ 2>/dev/null || true

    mkdir -p data-cache/implied-volatility
    cp impliedvol/*.json data-cache/implied-volatility/ 2>/dev/null || true

    echo "✅ Files copied (missing outputs skipped)"
```

- [x] Replace the existing "Copy all files to data repo" step with the version above

### 1.6 — Add data freshness heartbeat step

Add this step **between the copy step and the commit step**. It writes/updates
`data-cache/data_freshness.json` with per-section timestamps for only the
sections that produced output files this run.

```yaml
- name: Update data freshness
  if: steps.hours_check.outputs.in_market_hours == 'true'
  run: |
    python3 << 'EOF'
    import json, os
    from datetime import datetime, timezone
    from pathlib import Path

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fp = Path('data-cache/data_freshness.json')
    data = json.loads(fp.read_text()) if fp.exists() else {"sections": {}}

    section_sentinels = {
        "advance-decline":    "advancedecline/daily_breadth.json",
        "major-indexes":      "majorindexes/us_major_snapshot.json",
        "meanreversion":      "meanreversion/price_vs_ma_snapshot.json",
        "implied-volatility": "impliedvol/vix_options_snapshot.json",
    }
    for section, sentinel in section_sentinels.items():
        if Path(sentinel).exists():
            data["sections"][section] = {"last_updated": now}
            print(f"  ✅ {section}: {now}")
        else:
            existing = data.get("sections", {}).get(section, {}).get("last_updated", "never")
            print(f"  ⏭  {section}: no output, keeping {existing}")

    data["last_updated"] = now
    fp.write_text(json.dumps(data, indent=2))
    print("✅ data_freshness.json written")
    EOF
```

> **Note:** Verify the sentinel filenames match actual output filenames before
> deploying. Run each script locally and check what `.json` files it produces.
> Common candidates: `us_major_snapshot.json`, `price_vs_ma_snapshot.json`.

- [x] Verify sentinel filenames by checking output of each script
- [x] Add the "Update data freshness" step between copy and commit
- [x] Add `data_freshness.json` to the `git add` line in the commit step:
  ```yaml
  git add advance-decline/ major-indexes/ meanreversion/ implied-volatility/ cache/ data_freshness.json
  ```

---

## Phase 2 — Nightly & twice-daily workflows

Same isolation pattern: `continue-on-error: true` on each collector step,
resilient `cp`, and appropriate job timeout.

### 2.1 — `economy-indicators.yml`

This is the highest-risk nightly workflow: 6 sequential FRED collectors, one
failure currently blocks all 5 others and the commit.

- [x] Add `timeout-minutes: 10` to the job
- [x] Add `continue-on-error: true` to each of these steps:
  - `Fetch growth & output data`
  - `Fetch inflation & prices data`
  - `Fetch labor & employment data`
  - `Fetch money markets data`
  - `Fetch consumer & credit data`
  - `Fetch housing & affordability data`
- [x] Make copy step resilient — replace each `cp` with `cp ... 2>/dev/null || true`
- [x] Add "Update data freshness" step (sections: `economy-breadth`, `consumer-credit`, `housing-affordability`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.2 — `earnings.yml`

- [x] Add `timeout-minutes: 10` to the job
- [x] Add `continue-on-error: true` to:
  - `Fetch earnings calendar`
  - `Fetch earnings surprises`
- [x] Make copy step resilient (`cp ... 2>/dev/null || true` on both lines)
- [x] Add "Update data freshness" step (sections: `earnings-calendar`, `earnings-surprises`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.3 — `analyst-trends.yml`

- [x] Add `timeout-minutes: 10` to the job
- [x] Add `continue-on-error: true` to:
  - `Fetch recommendation trends`
  - `Aggregate by sector`
- [x] Make copy step resilient
- [x] Add "Update data freshness" step (section: `analyst-trends`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.4 — `sp-growth.yml`

`sp-growth` hits SEC EDGAR + 3-source fallback for 500 tickers. It legitimately
needs more time than the other nightly workflows.

- [x] Add `timeout-minutes: 30` to the job
- [x] Add `continue-on-error: true` to `Fetch S&P growth metrics`
- [x] Make copy step resilient (both `if` blocks already guard with `-f` checks; add `|| true` after the `cp` commands inside them)
- [x] Add "Update data freshness" step (sections: `sp100growth`, `sp500growth`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.5 — `options-whales.yml`

- [x] Add `timeout-minutes: 20` to the job
- [x] Add `continue-on-error: true` to `Fetch options whale trades`
- [x] Make copy step resilient: `cp optionswhales/*.json data-cache/options-whales/ 2>/dev/null || true`
- [x] Add "Update data freshness" step (section: `options-whales`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.6 — `stock-whales.yml`

- [x] Add `timeout-minutes: 20` to the job
- [x] Add `continue-on-error: true` to `Fetch stock whale trades`
- [x] Make copy step resilient: `cp stockwhales/*.json data-cache/stock-whales/ 2>/dev/null || true`
- [x] Add "Update data freshness" step (section: `stock-whales`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.7 — `etf-fund-flows.yml`

- [x] Add `timeout-minutes: 15` to the job
- [x] Add `continue-on-error: true` to `Generate ETF fund flows`
- [x] Make copy step resilient: `cp etffundflows/output/*.json data-cache/etf-fund-flows/ 2>/dev/null || true`
- [x] Add "Update data freshness" step (section: `etf-fund-flows`)
- [x] Add `data_freshness.json` to `git add` in commit step

### 2.8 — `support-resistence.yml` (was missing from original plan)

Runs daily at 5am ET on Alpaca API. Same failure profile as the whale workflows —
no timeout, no `continue-on-error`, has commented-out EDT cron variant.

- [x] Add `timeout-minutes: 15` to the job
- [x] Add `continue-on-error: true` to `Fetch support / resistence levels`
- [x] Copy step already has `2>/dev/null || echo "..."` — change `|| echo` to `|| true` for consistency
- [x] Add "Update data freshness" step (section: `support-resistance`)
- [x] Add `data_freshness.json` to `git add` in commit step
- [x] Add `"support-resistance"` to the `data_freshness.json` schema — implemented in 2.8 freshness step; `data-freshness.ts` types define it as a `KnownSection`

### 2.9 — `daily-news.yml` (paused — remove schedule)

The README says "currently paused; manual runs only." The workflow has two live
cron lines that silently consume the `deanfi-data-repo` concurrency queue twice
a day and block everything queued behind them if they hang.

- [x] Remove the entire `schedule:` block from `daily-news.yml`, leaving only `workflow_dispatch`
- [x] Update README table: change "Manual (schedule paused)" to "Manual only"

---

## Phase 3 — DST / cron cleanup (remaining workflows)

The nightly workflows (analyst-trends, earnings, sp-growth) run at 3–4am UTC
(10–11pm ET). A 1-hour DST drift is acceptable there — skip DST fix for these.

The twice-daily and business-hours workflows need fixing.

### 3.1 — `options-whales.yml` and `stock-whales.yml`

Replace commented EST/EDT pairs with single times that are acceptable for both.
Running 1 hour late during DST is fine for twice-daily whale data.

**options-whales.yml — replace schedule block with:**
```yaml
on:
  schedule:
    - cron: '0 17 * * 1-5'    # ~noon ET (12pm EST / 1pm EDT)
    - cron: '0 2 * * 2-6'     # ~9pm ET (9pm EST / 10pm EDT)
  workflow_dispatch:
    ...
```

- [x] Replace the 4-line EST+commented-EDT schedule in `options-whales.yml` with the 2-line version above
- [x] Same treatment for `stock-whales.yml` (crons: `30 17 * * 1-5` and `30 2 * * 2-6`)

### 3.2 — `economy-indicators.yml`

FRED data updates monthly or weekly — 1-hour DST drift is irrelevant. Use single
fixed UTC times and accept the offset rather than double-firing.

```yaml
on:
  schedule:
    - cron: '0 14 * * 1-5'   # ~8am ET (9am EST / 10am EDT — acceptable drift)
    - cron: '0 17 * * 1-5'   # ~noon ET (12pm EST / 1pm EDT — acceptable drift)
```

- [x] Replace the two active cron lines + two commented-out EDT cron lines with
  the two lines above (remove the comments entirely)

### 3.3 — `support-resistence.yml`

Currently `0 10 * * 1-5` (5am EST / 6am EDT) with a commented EDT variant. This
runs before market open — 1-hour drift is harmless. No change needed unless it
causes issues.

- [x] Review and confirm no change needed — 1-hour DST drift before market open is harmless; keeping `0 10 * * 1-5`

---

## Phase 4 — Move price cache out of git

The `market-data-10min` workflow currently commits `cache/` (parquet files) to
`deanfi-data` on every run — up to ~60 commits/day of binary blobs that don't
delta-compress in git. This bloats the data repo over time and slows every
workflow's `actions/checkout` step. Switch to `actions/cache` instead.

### 4.1 — Add cache restore/save steps to `market-data-10min.yml`

Add these two steps: one **before** "Create cache directory" (to restore), and
`actions/cache` handles the save automatically as a post-job step.

```yaml
- name: Get date for cache key
  id: cache_date
  run: echo "date=$(date -u +%Y-%m-%d)" >> $GITHUB_OUTPUT

- name: Restore price cache
  uses: actions/cache@v4
  with:
    path: ./cache
    key: market-data-cache-${{ steps.cache_date.outputs.date }}
    restore-keys: |
      market-data-cache-
```

- [x] Add "Get date for cache key" step after "Install dependencies"
- [x] Add "Restore price cache" step immediately after

### 4.2 — Update cache directory path in collection steps

The cache was previously at `data-cache/cache` (inside the data repo checkout).
Move it to `./cache` in the workspace root.

- [x] Change "Create cache directory" step from `mkdir -p data-cache/cache` to `mkdir -p ./cache`
- [x] Update every `--cache-dir ../data-cache/cache` argument in collection steps to `--cache-dir ../cache`
  - `fetch_daily_breadth.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - `fetch_ad_line_historical.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - `fetch_ma_percentage_historical.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - `fetch_highs_lows_historical.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - `fetch_volume_metrics_historical.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - All `majorindexes/` scripts with `--cache-dir ../data-cache/cache`
  - `fetch_price_vs_ma.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`
  - `fetch_ma_spreads.py --cache-dir ../data-cache/cache` → `--cache-dir ../cache`

### 4.3 — Remove cache from git operations

- [x] Remove `cache/` from the `git add` line in the commit step (done in Phase 1.6 — now includes `data_freshness.json` instead)
- [x] Add `cache/` to `.gitignore` in the `deanfi-data` repo to prevent accidental re-addition
- [x] If a `cache/` directory already exists in `deanfi-data`, remove it:
  `git rm -r --cached cache/` in the data repo (one-time cleanup commit) — 16 parquet/metadata files untracked; changes staged, ready to commit

---

## Phase 5 — `data_freshness.json` schema

All "Update data freshness" steps added in Phases 1–2 write to this file.
Define the schema once here for reference.

**Merge conflict strategy:** Drop the top-level `last_updated` field. Each
workflow writes only its own non-overlapping section keys. Git's line-level
merge on `git pull --rebase` handles non-overlapping JSON edits cleanly.

**Location in data repo:** `deanfi-data/data_freshness.json`

```json
{
  "sections": {
    "advance-decline":      { "last_updated": "2026-05-07T17:30:00Z" },
    "major-indexes":        { "last_updated": "2026-05-07T17:30:00Z" },
    "meanreversion":        { "last_updated": "2026-05-07T17:30:00Z" },
    "implied-volatility":   { "last_updated": "2026-05-07T17:28:00Z" },
    "earnings-calendar":    { "last_updated": "2026-05-07T03:45:00Z" },
    "earnings-surprises":   { "last_updated": "2026-05-07T03:45:00Z" },
    "analyst-trends":       { "last_updated": "2026-05-07T03:00:00Z" },
    "economy-breadth":      { "last_updated": "2026-05-07T17:00:00Z" },
    "consumer-credit":      { "last_updated": "2026-05-07T17:00:00Z" },
    "housing-affordability":{ "last_updated": "2026-05-07T17:00:00Z" },
    "sp100growth":          { "last_updated": "2026-05-07T04:15:00Z" },
    "sp500growth":          { "last_updated": "2026-05-07T04:15:00Z" },
    "options-whales":       { "last_updated": "2026-05-07T17:00:00Z" },
    "stock-whales":         { "last_updated": "2026-05-07T17:30:00Z" },
    "etf-fund-flows":       { "last_updated": "2026-05-07T21:45:00Z" }
  }
}
```

- [x] Confirm section keys match the directory names used in deanfi-data — all match except `support-resistance` (directory is `supportresistence`; key is intentionally hyphenated)
- [x] Confirm section keys match what deanfi-website expects — `src/types/data-freshness.ts` defines `KnownSection` as the canonical list; all collector keys use these names

---

## Phase 6 — deanfi-website integration

The website fetches data from raw GitHub URLs. Add freshness awareness.

- [x] Fetch `data_freshness.json` on page load (or at the same interval as other data)
- [x] For each data section on the site, display "Updated X min ago" using the section's `last_updated`
- [x] Fetch `data_freshness.json` from `https://r2.deanfi.com/data_freshness.json`
  directly (same R2 bucket as all other dashboard data — no special proxy needed)
- [x] Show a "data may be delayed" banner if any high-frequency section has
  `last_updated` older than **55 minutes** — worst-case latency is ~16 min
  (10-min cycle + 1-min R2 sync + 5-min React Query), so 55 min gives a buffer
  before users hit the 60-minute wall
- [x] Show a "data may be delayed" banner for nightly sections if `last_updated` is
  older than 26 hours (24h + 2h buffer)
- [x] Display "Updated X min ago" per section using each section's `last_updated`
- [x] Note: `data_freshness.json` is written to `deanfi-data` by each workflow
  and automatically synced to R2 by `sync-to-r2.yml` — no extra wiring needed

---

---

## Phase 7 — R2 sync reliability (deanfi-data repo)

The `sync-to-r2.yml` workflow in `deanfi-data` is a second failure point between
collectors and the website. If it fails (expired Cloudflare API token, Wrangler
version issue, R2 quota), data sits in GitHub but never reaches R2, and the website
sees stale data even though all collectors ran perfectly.

- [x] **Add `continue-on-error: false` explicitly and a failure summary step** to
  `sync-to-r2.yml` so failed syncs are visible in the Actions tab
- [ ] **Enable GitHub Actions failure email notifications** for the `deanfi-data`
  repo in GitHub account settings (Settings → Notifications → Actions). Free,
  zero code — catches `sync-to-r2.yml` failures within minutes.
- [ ] **Check `sync-to-r2.yml` run history** to see if R2 sync failures are already
  happening silently — this may already be a source of the staleness the website
  experiences
- [x] **Consider adding `data_freshness.json` to the R2 sync watch** — `sync-to-r2.yml`
  already syncs all `*.json` files on push, so `data_freshness.json` will be
  included automatically once it exists in `deanfi-data`
- [x] **Verify R2 sync excludes `cache/` directory** — the existing filter
  `grep -v '^cache/'` in `sync-to-r2.yml` already handles this

## Phase 7b — `combine-daily-snapshots.yml` (deanfi-data repo)

Runs at 5:15pm ET daily. Combines all data into `market_snapshot.json` and
uploads directly to R2. Low failure risk (reads local files, no external APIs)
but has no timeout and a manual DST cron comment.

- [x] Add `timeout-minutes: 10` to the `combine-snapshots` job
- [x] Fix DST cron: replace `15 22 * * 1-5` with `15 21,22 * * 1-5` to cover
  both EST (22:15 UTC = 5:15pm) and EDT (21:15 UTC = 5:15pm) year-round

---

## Summary of changes by file (updated)

| File | Changes |
|---|---|
| `market-data-10min.yml` | Cron consolidation, timeout, market-hours guard, continue-on-error ×9, resilient cp, freshness step, actions/cache for parquet |
| `economy-indicators.yml` | Cron consolidation, timeout, continue-on-error ×6, resilient cp, freshness step |
| `earnings.yml` | Timeout, continue-on-error ×2, resilient cp, freshness step |
| `analyst-trends.yml` | Timeout, continue-on-error ×2, resilient cp, freshness step |
| `sp-growth.yml` | Timeout (30m), continue-on-error ×1, resilient cp, freshness step |
| `options-whales.yml` | Cron consolidation, timeout, continue-on-error ×1, resilient cp, freshness step |
| `stock-whales.yml` | Cron consolidation, timeout, continue-on-error ×1, resilient cp, freshness step |
| `etf-fund-flows.yml` | Timeout, continue-on-error ×1, resilient cp, freshness step |
| `support-resistence.yml` | Timeout, continue-on-error ×1, resilient cp, freshness step |
| `daily-news.yml` | Remove `schedule:` block (truly paused — manual only) |
| `deanfi-data` repo | Add `cache/` to `.gitignore`, one-time `git rm -r --cached cache/` cleanup |
| `deanfi-website` | Read data_freshness.json, display per-section staleness, show delay banner |

---

## Recommended implementation order

1. `market-data-10min.yml` — biggest impact, most runs per day
2. `economy-indicators.yml` — most steps, highest nightly failure risk
3. `earnings.yml` + `analyst-trends.yml` — quick wins, two steps each
4. `sp-growth.yml` — long-running, needs careful timeout tuning
5. `options-whales.yml` + `stock-whales.yml` — cron + isolation fixes
6. `support-resistence.yml` — same pattern as whales, one collector
7. `daily-news.yml` — resolve paused/active ambiguity first
8. `etf-fund-flows.yml` — daily, lower urgency
9. Website freshness UI — can be done in parallel with any of the above
