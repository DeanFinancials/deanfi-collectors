# Batch download for `fetch_sectors.py` sector ETFs

### Parent PRD

`PRD-yfinance-rate-limit-resilience.md` — "Remaining work: Ticker batching in `majorindexes/fetch_sectors.py`"

### Type

AFK

### What to build

Replace the 11 per-ticker `Ticker.history()` calls in `fetch_sectors.py` with a single `yf.download([...])` call for all 11 GICS sector ETFs (XLK, XLV, XLF, XLY, XLI, XLP, XLE, XLB, XLC, XLU, XLRE), cutting Yahoo Finance requests from 11 to 1 for this collector.

Split per-ticker results from the MultiIndex batch response using `df[symbol]` after confirming `isinstance(df.columns, pd.MultiIndex)`. Count tickers that produced non-empty DataFrames and pass that count to the existing `assert_enough_succeeded` call. Wrap the batch call with `with_429_retry`.

Add tests for the new behavior to `tests/test_batch_fetch.py`.

### Status

**Completed 2026-05-21.** Implemented via `_batch_download_sectors` in
`majorindexes/fetch_sectors.py`, using one `yf.download([...])` call for the 11
sector ETFs, wrapped in `with_429_retry`, with per-ticker frames split from the
MultiIndex response via `df[symbol]`. Both snapshot and historical paths count
non-empty per-ticker frames and pass that count to `assert_enough_succeeded`.
Sector-specific coverage was added to `tests/test_batch_fetch.py`; focused
verification passes with `pytest tests/test_batch_fetch.py -q` (18 tests).

### Acceptance criteria

- [x] All 11 sector ETFs are fetched in a single `yf.download([...], …)` call rather than 11 separate `Ticker.history()` calls
- [x] The `yf.download` call is wrapped with `with_429_retry`
- [x] Per-ticker DataFrames are extracted from the MultiIndex response using `df[symbol]`
- [x] `assert_enough_succeeded` is called with the count of tickers that returned non-empty DataFrames
- [x] The script exits 1 and prints to stderr if all 11 tickers return empty (guard still fires)
- [x] The script exits 0 and produces valid output when at least 1 ticker returns data
- [x] Tests in `tests/test_batch_fetch.py` cover the scenarios listed in Testing notes

### User stories addressed

- User Story 15: single `yf.download` call for 11 sector ETFs
- User Story 17: `assert_enough_succeeded` still called after batch download

### Requirements addressed

- PRD Solution point 4: Batched ticker downloads
- PRD Implementation Decisions — Remaining work: Ticker batching in `fetch_sectors.py`

### Blocked by

None — can start immediately. Can be worked in parallel with issue 001.

### Implementation notes

- `fetch_sectors.py` already imports `with_429_retry`, `make_session`, and `assert_enough_succeeded` — no new imports needed
- `YF_SESSION = make_session()` is already module-level; pass `session=YF_SESSION` to `yf.download`
- The existing `assert_enough_succeeded` calls are at lines 278 and 348 — verify both are still wired after refactor
- The current `fetch_index_data()` helper fetches one symbol at a time; either remove it or leave it as a fallback for single-symbol callers (e.g., the benchmark fetch for `^GSPC`)
- The benchmark `^GSPC` fetch used for `sector_summary` computation may need to remain a separate call if it requires `.info` fields not available in the batch — check what data the benchmark path consumes
- Match the MultiIndex split pattern used in `fetch_volume_metrics_historical.py` for column extraction

### Testing notes

Add to `tests/test_batch_fetch.py` (create if not yet done by issue 001):

- Batch download returns a per-ticker DataFrame extracted correctly from a MultiIndex mock response (sectors variant — 11 symbols)
- Batch download returns an empty DataFrame for a sector ETF absent from the mock response
- `assert_enough_succeeded` is called with the correct success count after extraction
- `with_429_retry` wraps the `yf.download` call

### Risks and review notes

- The sector summary (`calculate_sector_summary`) consumes per-ticker fields like `daily_change_percent` and `1_month_percent` derived from historical data — verify these are correctly populated from the batch response before merging
- The benchmark `^GSPC` comparison logic may need a separate single-ticker fetch if it relies on `.info` fields — isolate and test that path separately
