# Chunk `fetch_volume_metrics_historical.py` S&P 500 bulk download

### Status

**Completed 2026-05-21.** Implemented in `advancedecline/fetch_volume_metrics_historical.py` via new `_download_chunked()` helper; tests in `tests/test_volume_metrics_chunking.py` (15 cases).

### Parent PRD

`PRD-yfinance-rate-limit-resilience.md` — "Remaining work: Volume metrics chunking in `advancedecline/fetch_volume_metrics_historical.py`"

### Type

AFK

### What to build

Split the `~500`-ticker S&P 500 universe download in `fetch_volume_metrics_historical.py` into chunks of at most 100 tickers, with a `time.sleep(5–10)` between each chunk. This is the highest-leverage remaining fix: this script is the primary rate-limit trigger identified in the 2026-05-20 incident — its single-burst bulk download exhausted Yahoo's rate-limit bucket before every subsequent collector even started.

The script currently passes the full universe to `download_market_data()` in one call. After this change, `download_market_data()` (or a new helper) should iterate over the universe in 100-ticker slices, concatenate the results, and sleep between slices. The rest of the script (metric computation, output writing) should be unchanged.

### Acceptance criteria

- [x] The S&P 500 universe download is split into slices of at most 100 tickers
- [x] A `time.sleep` of 5–10 seconds is inserted between each slice (not after the last one)
- [x] The concatenated result has the same shape as a single-call result would (all tickers present)
- [ ] The script still calls `assert_enough_succeeded` (or equivalent guard) after building per-ticker metrics, if applicable — **not applied: this script writes an aggregated time series, not per-ticker output; guard is N/A**
- [ ] A cold-cache run (no parquet cache present) completes without triggering a 429 cascade on the subsequent collector scripts — **pending live smoke test**
- [x] The chunking only applies on the non-cached path; `CachedDataFetcher` incremental updates are unaffected

### User stories addressed

- User Story 16: S&P 500 bulk download split into ≤100-ticker chunks with inter-chunk sleep

### Requirements addressed

- PRD Solution point 5: Volume metrics chunking
- PRD "Further Notes": `fetch_volume_metrics_historical.py` is the script that arms the rate limit for every collector that runs after it

### Blocked by

None — can start immediately.

### Implementation notes

- The full `~500`-ticker universe comes from `fetch_spx_tickers()` (from `shared/spx_universe.py`)
- `download_market_data()` currently has two paths: cached (`CachedDataFetcher`) and uncached (`yf.download`). Chunking is only needed on the uncached path — `CachedDataFetcher` already does incremental updates that naturally limit download size on warm-cache runs
- Recommended chunk size: 100 tickers. Sleep: `time.sleep(random.uniform(5, 10))` to avoid a fixed fingerprint, or `time.sleep(7)` as a simple constant — either is acceptable
- After chunking, concatenate chunk DataFrames with `pd.concat(chunk_dfs, axis=1)` before passing to `build_volume_metrics_series()`
- The script's `download_market_data()` function is a clean seam for this change — modify it rather than the main flow
- Wrap each chunk's `yf.download` call with `with_429_retry` if not already done via `CachedDataFetcher`

### Testing notes

No new automated tests are strictly required for this issue (the structural behavior — chunking and sleeping — is hard to unit-test without heavy mocking of `yf.download` + `time.sleep`). However:

- A manual smoke test on the cold-cache path (delete or bypass the parquet cache) should confirm the script runs to completion without a 429 error on a live run
- If a mock-based test is added, verify: `yf.download` is called `ceil(len(tickers) / 100)` times, and `time.sleep` is called `ceil(len(tickers) / 100) - 1` times

### Risks and review notes

- The primary risk is a subtle off-by-one in chunk boundaries causing duplicate or dropped tickers in the concatenated result — verify `len(result.columns)` equals `len(universe)` after concatenation
- Sleep adds latency: 5 chunks × 7s = ~35s added to the cold-cache path. Given the 10-minute workflow budget this is acceptable
- This fix guards the cold-cache and full-rebuild paths. The warm-cache incremental path (most common in production) is already low-volume and unaffected

### Implementation summary (2026-05-21)

Added `_download_chunked(tickers, *, period, chunk_size, sleep_seconds, download_fn, sleep_fn)` in `advancedecline/fetch_volume_metrics_historical.py`:

- Module constants `_CHUNK_SIZE = 100` and `_SLEEP_SECONDS = 7`
- Splits tickers into ≤100-ticker slices; sleeps 7s between slices (guarded by `if idx > 0` so no sleep after the last)
- Wraps each chunk's `yf.download` call with `with_429_retry`
- Concatenates with `pd.concat(chunk_dfs, axis=1)`
- `download_fn` / `sleep_fn` are injectable for test isolation; defaults are `yf.download` and `time.sleep`
- The cached (`CachedDataFetcher`) branch in `download_market_data()` is unchanged

Tests in `tests/test_volume_metrics_chunking.py` (15 cases) verify:
- Chunk and sleep call counts at `n_tickers ∈ {50, 100, 101, 500, 503}`
- All tickers present across chunks
- Each chunk ≤ 100 tickers
- No sleep after the last chunk
- `period` forwarded into each chunk call
- Uncached path delegates to `_download_chunked`; cached path does not
- `with_429_retry` invoked exactly once per chunk

Full test suite: 53 passed, 1 skipped (pre-existing curl_cffi skip).
