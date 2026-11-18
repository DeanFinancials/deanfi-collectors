# Engineering Requirements

Toolchain and engineering rules beyond the invariants in `AGENTS.md`.

## Toolchain

- Python 3.11 (what every workflow installs). Dependencies live in `requirements.txt`, as `>=` floors; install with `pip install -r requirements.txt`.
- `pytest` for Python tests (`pytest.ini` sets `testpaths = tests` and puts the repo root on the path). `dailynews/tests/` is outside the default path; run it explicitly.
- Node 24 only for the intraday scheduler (`scheduler/next-run.mjs`), tested with `node --test`.
- No linter or formatter is configured. Follow PEP 8 and the surrounding code.

## Data sources and limits

| Source | Key | Notes |
|---|---|---|
| Yahoo Finance via yfinance | none | Unofficial; rate-limits runners with HTTP 429. Batch downloads, use `CachedDataFetcher` and the guards in `docs/architecture.md`. |
| Finnhub | `FINNHUB_API_KEY` | Free tier is 60 calls/minute. |
| FRED | `FRED_API_KEY` | Free tier is 120 calls/minute. |
| Alpaca Market Data | `ALPACA_API_KEY`, `ALPACA_API_SECRET` | Use `https://data.alpaca.markets`, not the trading API host. Collectors cap requests below the 200/minute free limit. |
| SEC EDGAR | none | Requires a descriptive User-Agent (`spgrowth/config.yml`). |

## Collector rules

- Put shared logic in `shared/` (S&P 500 universe, sectors, caching, FRED). Do not copy a universe or sector map into a collector.
- yfinance price history goes through `shared/cache_manager.py`. Snapshot scripts call `assert_enough_succeeded` from `shared/fetch_guard.py` before writing.
- Exit non-zero rather than write an empty or partial payload that would replace good data. Fail-closed contract outputs (`educationfacts/`, `gsctopics/`) write nothing on any source failure.
- Read settings from the collector's `config.yml` and secrets from environment variables only; never hardcode keys or write them to output.
- Write output with UTC ISO 8601 timestamps. Dataset outputs follow the existing shape: a `_README` block (title, description, metric explanations), `metadata` (generation time, source, counts) and the data body. Do not rename or reshape a published field without updating the website consumer in the same change.
- Add a test under `tests/` for new parsing, guard or publication logic. Network calls in tests must be mocked.

## Adding a collector

1. Create `<name>/` with `config.yml` and `fetch_<name>.py`, reusing `shared/` modules.
2. Add a workflow per `docs/workflows.md` (structure, concurrency, timeout, pinned actions, secrets).
3. Add the row to `docs/collectors.md` and, if the dataset needs explaining, a short `<name>/README.md`.
4. Run it locally, then with `workflow_dispatch`, and check the commit in `deanfi-data` and the R2 sync.
