# Architecture

How collected data moves from an external API to the DeanFi website, and the guards that keep bad data out of `deanfi-data`.

## Data flow

```
deanfi-collectors (this repo)
  └─ GitHub Actions workflow (.github/workflows/*.yml)
       └─ Python collector → writes JSON in its own directory
            └─ copied into a checkout of deanfi-data (data-cache/), committed, pushed
                  └─ deanfi-data: sync-to-r2.yml (runs on every push that changes JSON)
                        └─ Cloudflare R2 bucket (https://r2.deanfi.com)
                              └─ deanfi-website dashboards fetch JSON from R2
```

- `deanfi-data` (GitHub) is the source of truth for dashboard data. R2 is a downstream mirror maintained by the deanfi-data workflow sync-to-r2.yml; nothing in this repo writes to R2.
- The R2 sync is a second failure point. If the website shows stale data but collectors succeeded, check the sync-to-r2.yml run history in `deanfi-data`.
- The website reads `https://r2.deanfi.com/data_freshness.json`, which the workflows here update (see Freshness below).
- Worst-case latency from collection to a user seeing data is roughly 20 minutes: the 15-minute intraday cadence, about a minute of R2 sync, and the website's 5-minute client cache.
- `daily-news.yml` dispatches the deanfi-data workflow combine-daily-snapshots.yml after scheduled runs and manual runs with `dispatch_combine` set, which builds the Market Pulse input (see `docs/context.md`). That workflow's own cron is the fallback.

## Workflow anatomy

Every collector workflow follows the same shape:

1. Check out this repo and `deanfi-data` (into `data-cache/`, using the `DATA_REPO_TOKEN` secret).
2. Set up Python 3.11 and install `requirements.txt`.
3. Run collectors from their directories. Each writes JSON next to its script (outputs are gitignored here).
4. Copy outputs into `data-cache/<section>/` and update that section's `last_updated` in `data_freshness.json`.
5. Validate, then `git add <section paths> data_freshness.json` → `git commit` → `git pull --rebase origin main` → `git push`.

Exceptions:

- `market-data-intraday.yml` publishes through `scripts/publish_market_data.py` instead of `pull --rebase`. It fetches `origin/main`, re-applies the staged market files on a fresh worktree, re-runs the snapshot validator, and pushes. If another market batch landed during collection it keeps the remote batch and defers its own to the next run. Only non-fast-forward pushes are retried.
- `options-whales.yml` collects in one job (its own concurrency group, uploads an artifact) and publishes in a short second job that holds the `deanfi-data-repo` lock.
- `education-facts.yml`, `gsc-topics.yml` and `etf-fund-flows.yml` are fail-closed (no `continue-on-error`): a failed source fails the job, every publish step is skipped, and the last good file stays in place.
- `etf-fund-flows.yml` seeds `etffundflows/output/` with the published month files before generating, because each day's flow needs the prior session's AUM and NAV. A first run with nothing to seed is not a failure (tickers get `missing_prior_day`). Since the seeded files are always present, it refreshes `last_updated` only when the copy actually changed `etf-fund-flows/` in deanfi-data.
- `analyst-trends.yml` and `support-resistence.yml` run at a fixed New York time year-round: both UTC crons fire, and a `dst-gate` job (`scripts/ny_hour_gate.py`) passes only the run scheduled for the intended local hour, judged by the cron that fired so late starts still count. The other run skips the publish job and succeeds without touching deanfi-data or the lock. Manual runs always proceed.
- `ci.yml` only runs the test suites (push and pull request, read-only token); it never checks out or writes deanfi-data.

Failure isolation differs by workflow. Economy, analyst trends and similar multi-script workflows mark collector steps `continue-on-error: true` and copy with `2>/dev/null || true`, so one failed source still publishes the rest. The market-data workflows run breadth, index and mean-reversion steps with `set -euo pipefail` (any failure aborts the publish); only implied volatility is best-effort.

## Concurrency

Every job that pushes to `deanfi-data` uses:

```yaml
concurrency:
  group: deanfi-data-repo
  queue: max
  cancel-in-progress: false
```

This serialises pushes. `queue: max` keeps every pending run queued; without it GitHub keeps only one pending run and cancels older ones. Because a hung job blocks the whole queue, every job sets `timeout-minutes` (see `docs/workflows.md`). Jobs that do not push (the intraday `schedule-next` timer, the options-whales collect job, `ci.yml`) use their own groups so they never hold the lock; the `dst-gate` jobs take no lock.

## Intraday scheduling

GitHub cron can run hours late or be dropped, so `market-data-intraday.yml` chains itself: after each run a slim `schedule-next` job waits and dispatches the next run 15 minutes after the current one started. Cron (`7,22,37,52 8-21 * * 1-5` UTC) is a bootstrap and backup. `scripts/check_market_collection.py` decides whether a run collects: only weekdays 08:00–17:00 America/New_York, and not if all four market sections were published in the last 10 minutes. Details, the disable switch and costs are in `scheduler/README.md`.

`market-data-close.yml` runs once after the close (21:20 UTC) as a safety net so the closing session is always captured.

## Price cache

yfinance price history is cached as parquet by `shared/cache_manager.py` (`CachedDataFetcher`): under 24 hours old it re-downloads the last 5 calendar days (through today), 24–168 hours the last 10, older than that a full rebuild. The incremental window also reaches 7 calendar days before the cache's last date, so it overlaps cached full sessions across weekends and holidays. The fresh download replaces every cached row from its first date on, so the close run overwrites a partial intraday bar for today with the final bar. Prices are dividend- and split-adjusted (`auto_adjust=True`), and Yahoo rescales all earlier history after an ex-dividend date or a split, so before merging the fetcher compares the fresh Open/High/Low/Close with the cache on the overlapping dates, skipping each frame's newest date (a possible partial bar). If any ticker differs by more than 1e-5 relative, it re-downloads the full requested period or date range and saves that instead, so the cache matches a fresh full download. As a backstop the metadata records `full_download_at` (incremental saves carry it forward), and a full download is forced when it is older than 168 hours or missing. If a forced full download fails, a run that disallows stale data returns an empty frame; otherwise the fetcher does the incremental update as usual and retries the full download on the next run (`tests/test_cache_manager.py`). If a refresh download fails, the fetcher returns the stale cache by default (the intraday run accepts best-effort freshness); `market-data-close.yml` sets `PRICE_CACHE_ALLOW_STALE=false` on its job, so there a failed refresh returns an empty frame and the collector fails instead of publishing intraday or stale bars as the close (`tests/test_close_fail_closed.py`). If the incremental download succeeds but the cached parquet cannot be read (corrupt, missing or a read error), the fetcher does not return or save the short incremental frame: it re-downloads the full requested period or date range, as a cold cache does, and saves that. If that download also fails, it returns an empty frame and leaves the cache files untouched, whatever the stale setting. Metadata is written only after its parquet saves, from the same frame (`tests/test_cache_manager.py`). In CI the cache directory is persisted with `actions/cache` in `market-data-intraday.yml` and `market-data-close.yml`, which share one key scheme (`market-data-cache-<UTC date>-<run id>`, restoring the newest same-day cache, else the newest overall): the close run starts from the day's intraday cache, and its saved cache, holding the closing bars, warms the next morning's first intraday run. A job that passes `--cache-dir` must restore it first (`tests/test_workflow_price_cache.py`). Cache keys change when a script's symbol set or key scheme changes, so each fetch also records its cache name and time in `price_cache_usage.json` in the cache directory (the entry's own files change only when it saves), and both workflows run `scripts/prune_price_cache.py --cache-dir ./cache` after the collectors. `actions/cache` saves the directory in its post step at job end, so the pruned directory is what the next run restores. The prune (`prune_unused_cache` in `shared/cache_manager.py`) deletes each parquet/metadata pair that has been neither saved (metadata `last_update`) nor requested for 14 days, and any parquet or metadata file missing its partner; it reads recorded timestamps, not file mtimes. Every successful market run requests every live key, so live keys go at most a long weekend unrequested, and an entry unused for over 168 hours would be fully re-downloaded on its next use anyway; a pruned key that is requested again cold-starts with one full download. The prune touches only top-level cache files (no subdirectories or symlinks), logs errors instead of raising, always exits 0 and runs with `continue-on-error` (`tests/test_price_cache_prune.py`). It is never committed to `deanfi-data`; do not add `cache/` to any `git add` line.

## Data-quality guards

Yahoo Finance rate-limits runners (HTTP 429) and can return nonempty responses with null closes. Collectors must fail rather than overwrite good data with empty or null payloads. The layers:

- `shared/fetch_guard.py` (`assert_enough_succeeded`): a collector exits 1 without writing when zero tickers succeed, so the workflow never stages an empty file. Callers: every collector in `majorindexes/` and `meanreversion/`, which guard each snapshot and historical file before writing it (`fetch_ma_spreads.py` checks both before writing either; `us_major_etf_prices.json` is unguarded); the yfinance snapshot scripts in `impliedvol/`; `etffundflows/fetch_etf_fund_flows.py` (a ticker succeeds when its session point has AUM); and `spgrowth/fetch_sp_growth.py`, which counts the companies each universe file would publish and, if either `sp100growth.json` or `sp500growth.json` would have none, writes neither.
- `PRICE_CACHE_ALLOW_STALE=false` (close run only): the price cache never stands in for a failed download; see [Price cache](#price-cache).
- `shared/yf_retry.py` (`with_429_retry`): retries a yfinance call after a sleep on rate-limit errors (default one retry after 30 seconds), and optionally on empty or all-null frames.
- `shared/yf_session.py` (`make_session`): a curl_cffi session impersonating Chrome, which Yahoo blocks less often; falls back to yfinance's default transport.
- Snapshot generation rejects unusable latest or prior closes, sector success counts reflect emitted observations, and daily breadth needs usable current/prior close pairs (`tests/test_daily_breadth_validity.py`).
- `scripts/validate_snapshots.py`: run in `data-cache/` before every market-data commit. It compares each snapshot with `HEAD` and refuses to replace a non-empty body with an empty one, and rejects null sector prices, empty breadth observations and malformed or non-finite JSON.
- Before copying, both market workflows require a trading date in `daily_breadth.json`; the intraday workflow also requires at least four indices in `us_major_indices.json`.

A failed run leaves the previous files in `deanfi-data`; the next successful run replaces them.

## Freshness

Workflows write `data_freshness.json` at the root of `deanfi-data` with `sections.<section>.last_updated` (UTC ISO 8601) for each section they publish. Freshness is tracked per section, not per workflow. `daily-news.yml` updates `metadata.json` instead; `education-facts.yml` and `gsc-topics.yml` publish under `education/` without a freshness entry.
