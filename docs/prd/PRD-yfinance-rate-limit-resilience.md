# PRD: yfinance Rate-Limit Resilience

_Derived from INCIDENT-2026-05-20-yfinance-rate-limit.md_

---

## Problem Statement

During the 20:31 UTC run on 2026-05-20, Yahoo Finance rate-limited every ticker
fetch in the `deanfi-collectors` market-data workflow. Each `fetch_*.py` script
caught the per-ticker exceptions, wrote an empty JSON payload to disk (`"indices":
{}`, `"sectors": {}`, `"data": {}`), printed `✅ Saved snapshot`, and exited 0.
The CI workflow saw a diff, committed the empty files on top of the previous good
data, and pushed them to `deanfi-data`. The downstream `combine-daily-snapshots`
workflow then ingested those empty payloads and produced a `market_pulse_input.json`
missing nine `core.*` fields, causing the Market Pulse validation step to fail and
blocking that night's automated article.

The rate limit itself was triggered by `fetch_volume_metrics_historical.py`
bulk-downloading ~500 S&P 500 tickers in a single call immediately before the
per-ticker collectors ran. Once Yahoo's rate limit was active, every subsequent
collector got HTTP 429 for every ticker.

No data was permanently lost — yfinance returns full history on every call, so
the next clean run rebuilds `*_historical.json` from scratch. The real bug was
that the collector scripts treated zero successful fetches as a success, causing
silent corruption of the data pipeline.

---

## Solution

A layered defense against silent empty writes and rate-limit-triggered data
corruption:

1. **Per-script fetch guard** — each `fetch_*.py` script refuses to write its
   output JSON if zero tickers succeeded, exiting 1 so CI never commits the
   empty payload.

2. **429 retry + Chrome session** — shared helpers retry yfinance calls once after
   sleeping 30s on a rate-limit error, and present Yahoo's bot-detection filters
   with a Chrome-impersonating curl_cffi session.

3. **CI commit-time validator** — a standalone script (`validate_snapshots.py`)
   runs before `git commit` in the `market-data-10min` workflow and refuses to
   commit any snapshot whose body dict went from non-empty in `HEAD` to empty in
   the working tree.

4. **Batched ticker downloads** — replace the per-ticker `Ticker.history()` loops
   in the highest-volume collectors with single `yf.download([...])` calls,
   cutting request count by 6–11× for the major-indexes and sector collectors.

5. **Volume metrics chunking** — split `fetch_volume_metrics_historical.py`'s
   S&P 500 bulk download into chunks with inter-chunk sleeps, since that bulk
   download is the primary trigger that exhausts Yahoo's rate limit bucket before
   the subsequent collectors even start.

---

## User Stories

1. As a data engineer, I want a collector script to exit with a non-zero code when
   zero tickers return data, so that CI never commits an empty snapshot on top of
   previously-good data.

2. As a data engineer, I want a zero-success exit to print a clear error to stderr
   with the label, success count, and total attempted, so that I can diagnose the
   failure from CI logs without reading Python code.

3. As a data engineer, I want the fetch guard to be a no-op when zero tickers are
   attempted (e.g., empty input list), so that scripts with no ticker configuration
   are not accidentally broken.

4. As a data engineer, I want the fetch guard to pass when at least one ticker
   succeeds, even if others fail, so that partial results are always preferred over
   no commit.

5. As a data engineer, I want a shared `with_429_retry()` helper that retries a
   yfinance call once after sleeping 30 seconds on a rate-limit error, so that
   transient 429s are recovered without manual re-runs.

6. As a data engineer, I want the retry helper to detect rate-limit errors by class
   name substring (`RateLimit`) and message substring (`429`), so that it remains
   resilient across yfinance version changes that rename the exception class.

7. As a data engineer, I want the retry helper to immediately re-raise non-rate-limit
   exceptions without sleeping, so that real errors (bad symbols, network failures)
   surface quickly.

8. As a data engineer, I want a shared `make_session()` factory that returns a
   curl_cffi Chrome-impersonating session for yfinance, so that Yahoo's bot
   detection is less likely to trigger rate limits in the first place.

9. As a data engineer, I want `make_session()` to fall back to `None` if curl_cffi
   is not installed, so that the factory is safe to call in all environments
   without crashing.

10. As a data engineer, I want a CI commit-time validator script that compares
    each tracked snapshot's working-tree body dict against its HEAD version, and
    exits 1 if an empty dict would overwrite a non-empty one, so that corrupted
    payloads never reach `deanfi-data` even if a per-script guard is misconfigured
    or missing.

11. As a data engineer, I want the CI validator to skip files that are not on disk,
    new files with no HEAD version, and payloads without a recognized body key
    (`indices`/`sectors`/`data`), so that validators do not produce false positives
    on legitimate first writes or format changes.

12. As a data engineer, I want the CI validator to aggregate all failures before
    exiting 1, so that a single CI run surfaces all corrupted snapshots rather
    than stopping at the first.

13. As a data engineer, I want the `market-data-10min.yml` workflow to run the
    snapshot validator as a named step between "Copy all files to data repo" and
    "Commit and push", so that invalid data is caught before it enters the git
    history.

14. As a data engineer, I want `fetch_us_major.py` to fetch all 6 core US indices
    in a single `yf.download(['^GSPC', '^DJI', '^IXIC', '^NDX', '^RUT', '^VIX'], …)`
    call instead of 6 separate `Ticker.history()` calls, so that the request count
    is reduced by ~6× for this collector.

15. As a data engineer, I want `fetch_sectors.py` to fetch all 11 sector ETFs in a
    single `yf.download([...])` call instead of 11 separate calls, so that the
    request count is reduced by ~11× for this collector.

16. As a data engineer, I want `fetch_volume_metrics_historical.py` to split its
    S&P 500 universe download into chunks of at most 100 tickers, with a 5–10 second
    sleep between chunks, so that the bulk download no longer exhausts Yahoo's
    rate-limit bucket in a single burst, preventing the cascade that caused the
    2026-05-20 incident.

17. As a data engineer, I want every affected collector to still use
    `assert_enough_succeeded` after a batched download, so that the per-script
    guard still fires if the batch itself returns empty data.

18. As a market analyst, I want the Market Pulse Input to contain all nine
    required `core.*` fields on every run, so that automated article generation
    is not blocked by upstream data gaps.

19. As a market analyst, I want a failed collector run to leave yesterday's snapshot
    file in place in `deanfi-data`, so that the combine workflow uses stale-but-valid
    data rather than empty data on the rare occasion that a full run fails.

20. As a site visitor, I want the DeanFi dashboard to continue showing data even
    after a partially-failed collector run, so that transient Yahoo Finance errors
    do not cause visible data outages on the site.

21. As a site visitor, I want the "Updated X minutes ago" freshness indicator to
    remain accurate after a failed run, so that I know the most recently collected
    data's age rather than seeing a stale or incorrect timestamp.

22. As a developer onboarding to `deanfi-collectors`, I want the fetch guard to be
    in a single importable module (`shared/fetch_guard.py`) so I can wire it into
    new collectors without copy-pasting logic.

23. As a developer onboarding to `deanfi-collectors`, I want a structural test that
    verifies every listed `fetch_*.py` script imports `assert_enough_succeeded` and
    calls it before each `save_json()` site, so that I am alerted by CI if a new
    script or new save call forgets the guard.

24. As a developer onboarding to `deanfi-collectors`, I want a comment in
    `fetch_us_major.py` on the ETF prices save path (which is explicitly not guarded
    because it is a bulk download and a separate concern) so that the absence of
    `assert_enough_succeeded` on that specific call does not look like an oversight.

25. As a DevOps engineer, I want R2 sync failures in `deanfi-data` to trigger a
    GitHub Actions failure email, so that silent R2 sync failures are surfaced within
    minutes rather than discovered hours later when the website is stale.

---

## Implementation Decisions

### Completed modules

**`shared/fetch_guard.py` — `assert_enough_succeeded(successful, total, *, label)`**
The guard is intentionally binary: it only fires when `successful == 0` and
`total > 0`. A percentage threshold was considered and rejected — losing any
individual ticker is preferable to blocking a commit when the majority succeeded.
The function prints to stderr (not stdout) so CI tools that grep for `❌` see
both the per-file detail and the summary.

**`shared/yf_retry.py` — `with_429_retry(fn, *args, retries=1, sleep_seconds=30.0, **kwargs)`**
Exception detection is by class-name substring and message substring rather than
importing `yfinance.exceptions.YFRateLimitError` directly, because that import
path has shifted across yfinance versions. Defaults: 1 retry, 30s sleep. The
market-data-10min workflow runs every 10 minutes, so 30s sleep + 1 retry adds at
most ~30s to the collector runtime within a 10-minute budget.

**`shared/yf_session.py` — `make_session()`**
Returns a `curl_cffi.requests.Session(impersonate="chrome")` or `None`. curl_cffi
is already a transitive dependency of yfinance. Falls back silently on ImportError
so development environments without curl_cffi installed don't break.

**`scripts/validate_snapshots.py`**
Runs from the `data-cache/` root (the data repo checkout in CI). Checks a fixed
list of 8 snapshot files that were affected in the 2026-05-20 incident. Intentionally
excludes `meanreversion/price_vs_ma_snapshot.json` — its body shape (single-ticker
SPY snapshot, `"indices": {}`) can be legitimately empty in edge cases; the per-script
guard covers it instead. The validator runs as the "Validate snapshots (refuse empty
overwrite)" step between "Copy all files to data repo" and "Commit and push" in
`market-data-10min.yml`.

**9 `fetch_*.py` scripts updated**
All scripts listed in the incident now import `assert_enough_succeeded` from
`shared.fetch_guard`, `with_429_retry` from `shared.yf_retry`, and `make_session`
from `shared.yf_session`. Each script calls `assert_enough_succeeded` before every
`save_json()` call that writes a per-ticker output (snapshot and historical files).
The structural test `tests/test_fetch_scripts_guard.py` verifies this wiring at
the source level for all 9 scripts.

**`market-data-10min.yml` workflow**
Changes from the incident response:
- Single consolidated cron `5-55/10 12-21 * * 1-5` replacing dual EST/EDT pairs
- `timeout-minutes: 10` added to the job
- `continue-on-error: true` on all collection steps
- Resilient `cp … 2>/dev/null || true` in the copy step
- `actions/cache` for parquet price cache (removed git-committed `cache/` blob)
- Market-hours guard step gates all collection and copy steps
- "Validate snapshots" step runs `scripts/validate_snapshots.py` before commit

**Ticker batching in `majorindexes/fetch_us_major.py`** — **Completed 2026-05-21 (Issue 001).**
The 6 core US indices (`^GSPC`, `^DJI`, `^IXIC`, `^NDX`, `^RUT`, `^VIX`) are
now fetched in a single `yf.download([...])` call via a new
`_batch_download_indices(symbols, period)` helper, wrapped in `with_429_retry`.
Per-ticker frames are extracted from the MultiIndex response with
`df[symbol]` (guarded by `isinstance(df.columns, pd.MultiIndex)`), with
fallbacks for single-ticker flat-column, missing-symbol, empty, and `None`
response shapes. Both the snapshot and historical save paths still call
`assert_enough_succeeded` with the count of non-empty per-ticker frames.
The snapshot path now derives daily change from the dataframe itself via
`utils.get_current_snapshot(df)` instead of `Ticker.info['regularMarketChange']`
— deliberate, to eliminate per-ticker `.info` requests. See
`tests/test_batch_fetch.py` for behavior coverage (9 tests). The cold-cache
live smoke test (verify batched daily-change values match the prior
`Ticker.history()` + `Ticker.info` flow within tolerance, especially for
^VIX across long weekends) remains pending.

### Remaining work

**Ticker batching in `majorindexes/fetch_sectors.py`** — **Completed 2026-05-21 (Issue 002).**
The 11 sector ETFs (`XLK`, `XLV`, `XLF`, `XLY`, `XLI`, `XLP`, `XLE`, `XLB`,
`XLC`, `XLU`, `XLRE`) are now fetched in a single `yf.download([...])` call via
`_batch_download_sectors(symbols, period)`, wrapped in `with_429_retry`.
Per-ticker frames are extracted from the MultiIndex response with `df[symbol]`
after `isinstance(df.columns, pd.MultiIndex)`, with fallbacks for missing,
empty, `None`, and single-ticker flat-column responses. Both snapshot and
historical paths pass the count of non-empty per-ticker frames to
`assert_enough_succeeded`, so an all-empty sector batch exits before saving.
See `tests/test_batch_fetch.py` for behavior coverage (18 focused batch tests,
including the Issue 001 major-index tests and Issue 002 sector tests). The
cold-cache live smoke test remains pending.

**Volume metrics chunking in `advancedecline/fetch_volume_metrics_historical.py`** — **Completed 2026-05-21 (Issue 003).**
This script was the primary rate-limit trigger — it downloaded ~500 S&P 500 tickers
in one burst immediately before the per-ticker collectors ran. The uncached path
in `download_market_data()` now delegates to a new `_download_chunked()` helper
that splits the universe into ≤100-ticker slices with `time.sleep(7)` between
slices and wraps each chunk's `yf.download` call with `with_429_retry`. The
`CachedDataFetcher` path is unchanged. See `tests/test_volume_metrics_chunking.py`
for behavior coverage (15 tests). The cold-cache live smoke test remains pending.

**Workflow stagger (optional, low priority)**
The `market-data-10min.yml` "Fetch all index data" step runs 6 scripts sequentially
in one shell block. A simple `sleep 30` between scripts would spread the request
bursts across 3 minutes without requiring any Python changes. This is low priority
given that `with_429_retry` and per-ticker sleeps already absorb most transient
rate limits.

**R2 sync failure notifications (operational)**
Enable GitHub Actions failure email notifications for the `deanfi-data` repo
(Settings → Notifications → Actions). No code change. Also: review `sync-to-r2.yml`
run history to determine whether silent R2 sync failures are already occurring.

---

## Testing Decisions

**What makes a good test for this domain:**
Tests should verify the external behavior of each module — what it does when inputs
are well-formed, when inputs are at boundary conditions, and when downstream
dependencies fail. Tests must not assert on log messages as their primary signal
(they are allowed as secondary), must not import yfinance or pandas (use `importlib`
to load modules directly, bypassing `shared/__init__.py`'s heavy imports), and must
not hit the network.

**Modules with tests:**

`tests/test_fetch_guard.py` — covers `assert_enough_succeeded`:
- Exit 1 when successful=0 and total>0; stderr contains label, "0/N", "refusing"
- Returns None when at least one ticker succeeded
- No-op when total=0 (nothing attempted)
- All succeeded returns None
- Keyword-only `label` raises TypeError if called positionally

`tests/test_yf_helpers.py` — covers `with_429_retry` and `make_session`:
- Returns value on first success; no sleep called
- Retries on RateLimit-named exception; succeeds on retry
- Raises after exhausting retry budget
- Does not retry on non-rate-limit exceptions
- Matches "429" substring in exception message
- `make_session` returns None when curl_cffi unavailable (monkeypatched)
- `make_session` returns session object with `get` attribute when curl_cffi present

`tests/test_validate_snapshots.py` — covers `scripts/validate_snapshots.py` via
subprocess against a real throwaway git repo in `tmp_path`:
- Fails when empty dict would overwrite populated `indices`/`sectors`/`data` body
- Passes when new data is non-empty
- Passes when HEAD was already empty
- Passes on new file with no HEAD version
- Skips silently when file is not on disk
- Skips when payload has no recognized body key
- Aggregates multiple failures and reports all before exiting

`tests/test_fetch_scripts_guard.py` — structural test (source-text analysis):
- For each of the 9 listed scripts: imports `assert_enough_succeeded` from
  `shared.fetch_guard` and calls it before each `save_json()` site

**Tests to write for ticker batching (when implemented):**
Add to `tests/test_yf_helpers.py` or a new `tests/test_batch_fetch.py`:
- Batch download returns per-ticker DataFrame extracted from MultiIndex response
- Batch download returns empty DataFrame for a ticker not in the response
- `assert_enough_succeeded` is called with the correct success count after batch extraction
- `with_429_retry` wraps the `yf.download()` call (verify via mock)

**Prior art for test style:**
All existing tests use `importlib.util.spec_from_file_location` to load pure modules
without triggering heavy shared imports. The `validate_snapshots` tests create a real
git repo in `tmp_path` (via `subprocess.run(["git", "init", …])`). New tests should
follow the same patterns.

---

## Out of Scope

- **Switching data sources away from yfinance.** The rate limit is a known yfinance
  characteristic. The fixes make the pipeline resilient to it; migrating to a paid
  or more permissive data provider is a separate product decision.

- **Per-ticker percentage threshold in `assert_enough_succeeded`.** Blocking commits
  when fewer than 50% of tickers succeed was considered during the incident and
  rejected. The binary (zero-success) rule is simpler, more predictable, and less
  likely to block legitimate partial-success runs during real market hours.

- **Tightening the market-hours gate to 16:00 ET.** The incident's damaging run
  occurred at 16:31 EDT (within the current 8–17 window). Tightening to 16:00 would
  have prevented that specific run, but also silently drops ~6 scheduled runs during
  the trading day's final hour. The existing guard at 17:00 is the safer default.

- **Combine workflow or Market Pulse builder changes.** The incident confirmed that
  `combine_daily_snapshots.py` and the Market Pulse validator are working correctly.
  They accurately detected the empty payloads and failed loud. No changes required.

- **Historical file recovery.** No action needed — yfinance returns full history on
  every call, so the next successful run repopulates `*_historical.json` from scratch.

---

## Further Notes

**Implied vol filename open question — resolved.**
The incident noted a possible mismatch between `combine_daily_snapshots.py`'s loader
and the actual file on disk. Confirmed: `combine_daily_snapshots.py` line 744 reads
`implied-volatility/major_indices_iv_snapshot.json`, which matches the actual output
file from `impliedvol/fetch_major_indices_iv.py`. No change needed.

**Why some collectors survived the incident.**
`advancedecline/fetch_daily_breadth.py` and related scripts ran first and used a
warm cache (7.2h old), requiring only a 5-day incremental update rather than a full
download. `fetch_volume_metrics_historical.py` also survived because its cache had
already captured enough data before the rate limit hit mid-bulk-download. This
ordering effect means chunking `fetch_volume_metrics_historical.py` is the highest-
leverage remaining fix — it's the script that arms the rate limit for every
collector that runs after it.

**curl_cffi is a transitive dependency.**
`curl_cffi` is already pulled in by yfinance and does not need to be added to
`requirements.txt` explicitly. `make_session()` guards against it being missing
anyway.
