# Batch download for `fetch_us_major.py` core indices

### Parent PRD

`PRD-yfinance-rate-limit-resilience.md` — "Remaining work: Ticker batching in `majorindexes/fetch_us_major.py`"

### Type

AFK

### What to build

Replace the 6 per-ticker `Ticker.history()` calls for the core US indices (`^GSPC`, `^DJI`, `^IXIC`, `^NDX`, `^RUT`, `^VIX`) with a single `yf.download([...])` call, cutting Yahoo Finance requests from 6 to 1 for this collector.

The batched response is a multi-level DataFrame. After the download, split per-ticker using `df[symbol]` after confirming `isinstance(df.columns, pd.MultiIndex)`. Count the tickers that produced non-empty DataFrames and pass that count to the existing `assert_enough_succeeded` call. Wrap the `yf.download` call with `with_429_retry`.

The per-ticker `Ticker.history()` loop currently used for snapshot data and historical data should both be replaced. The ETF prices section (`fetch_latest_etf_prices`) already uses `yf.download` and does not need to change.

Add tests covering this new behavior to `tests/test_batch_fetch.py` (create if it does not exist).

### Status

**Completed 2026-05-21.** Implemented via `_batch_download_indices` helper in
`majorindexes/fetch_us_major.py` plus `tests/test_batch_fetch.py` (9 tests).
Cold-cache live smoke test still pending — verify a real run produces a
snapshot matching the previous `Ticker.history` + `Ticker.info` output within
expected tolerance (especially for ^VIX daily-change across long weekends).

### Acceptance criteria

- [x] The 6 core indices are fetched in a single `yf.download(['^GSPC', '^DJI', '^IXIC', '^NDX', '^RUT', '^VIX'], …)` call rather than 6 separate `Ticker.history()` calls
- [x] The `yf.download` call is wrapped with `with_429_retry`
- [x] Per-ticker DataFrames are extracted from the MultiIndex response using `df[symbol]`
- [x] `assert_enough_succeeded` is called with the count of tickers that returned non-empty DataFrames
- [x] The script exits 1 and prints to stderr if all 6 tickers return empty (guard still fires)
- [x] The script exits 0 and produces valid output when at least 1 ticker returns data
- [x] Tests in `tests/test_batch_fetch.py` cover the scenarios listed in Testing notes

### User stories addressed

- User Story 14: single `yf.download` call for 6 core US indices
- User Story 17: `assert_enough_succeeded` still called after batch download

### Requirements addressed

- PRD Solution point 4: Batched ticker downloads
- PRD Implementation Decisions — Remaining work: Ticker batching in `fetch_us_major.py`

### Blocked by

None — can start immediately.

### Implementation notes

- `fetch_us_major.py` already imports `with_429_retry`, `make_session`, and `assert_enough_succeeded` — no new imports needed
- `YF_SESSION = make_session()` is already module-level; pass `session=YF_SESSION` to `yf.download`
- The existing `assert_enough_succeeded` calls are at lines 379 and 482 — verify both are still wired after refactor
- The ETF prices section (function `fetch_latest_etf_prices`) already uses `yf.download` and is not in scope
- When the batch response is a single-ticker DataFrame, `df.columns` may not be a MultiIndex — handle that edge case
- Follow the MultiIndex split pattern already established in `fetch_volume_metrics_historical.py` (`data["Close"]`, `data["Volume"]` extraction) as a reference for column structure

### Testing notes

Create or extend `tests/test_batch_fetch.py` using `importlib.util.spec_from_file_location` (matching existing test style — do not import yfinance or pandas directly; use mocks):

- Batch download returns a per-ticker DataFrame extracted correctly from a MultiIndex mock response
- Batch download returns an empty DataFrame for a ticker absent from the mock response
- `assert_enough_succeeded` is called with the correct success count after extraction (verify via mock)
- `with_429_retry` wraps the `yf.download` call (verify via mock — retry is invoked, not `yf.download` directly)

### Risks and review notes

- The MultiIndex column structure from `yf.download` differs between single-ticker and multi-ticker calls; guard with `isinstance(df.columns, pd.MultiIndex)` before splitting
- Confirm the batched snapshot values (close, open, volume, etc.) match what the previous `Ticker.history()` + `Ticker.info` flow produced before merging — a side-by-side comparison on a live run is the most reliable check

### Implementation notes (post-merge)

- New helper `_batch_download_indices(symbols, period)` in `majorindexes/fetch_us_major.py`
  performs the batched `yf.download` (wrapped in `with_429_retry`) and returns
  `Dict[symbol, Optional[pd.DataFrame]]`. Handles MultiIndex, single-ticker
  flat-column, missing-symbol, empty, and `None` response shapes.
- Snapshot path now derives daily change from the dataframe itself via
  `utils.get_current_snapshot(df)` instead of `Ticker.info['regularMarketChange']`.
  This is a deliberate behavior change to eliminate per-ticker `.info` requests.
  Holiday-gap daily-change drift on ^VIX is the most likely place to notice
  any difference; flag if observed in live runs.
- `fetch_index_data` and `from shared.cache_manager import CachedDataFetcher`
  were removed from `fetch_us_major.py` (they were per-ticker code paths
  superseded by the batched call). Sibling `majorindexes/fetch_*.py` scripts
  still carry their own copies. The `--cache-dir` CLI flag is preserved as a
  no-op so `.github/workflows/market-data-10min.yml` does not need to change.
- Test file: `tests/test_batch_fetch.py` — follows the `importlib` + `sys.modules`
  stubbing pattern from `tests/test_volume_metrics_chunking.py`. 9 tests
  covering the 4 scenarios above plus single-ticker, missing-symbol, empty,
  and `None` response edge cases. Full suite: 62 passed, 1 skipped.
