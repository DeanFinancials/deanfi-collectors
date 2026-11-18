# Workflows

GitHub Actions in `.github/workflows/` run every collector and publish to `deanfi-data`. How a workflow is built (checkout, copy, freshness, commit, concurrency) is in `docs/architecture.md`; this page is the inventory and setup reference.

## Inventory

Cron is UTC. ET equivalents drift by an hour with daylight saving time unless noted; GitHub often starts scheduled runs late. Rows marked DST-gated list both UTC crons and run once at the stated New York time year-round (see `docs/architecture.md`).

| Workflow | Cron (UTC) | Roughly (ET) | Timeout (min) | Publishes |
|---|---|---|---|---|
| `market-data-intraday.yml` | `7,22,37,52 8-21 * * 1-5` plus self-dispatched handoffs | every 15 min, weekdays 08:00–17:00 ET (DST-safe) | 12 (+15 timer job) | advance-decline, major-indexes, meanreversion, implied-volatility |
| `market-data-close.yml` | `20 21 * * 1-5` | 4:20pm EST / 5:20pm EDT | 15 | same four sections, after the close |
| `economy-indicators.yml` | `0 14 * * 1-5`, `0 17 * * 1-5` | 9am & 12pm EST / 10am & 1pm EDT | 10 | economy-breadth, consumer-credit, housing-affordability |
| `etf-fund-flows.yml` | `45 21 * * 1-5` | after the close | 15 | etf-fund-flows |
| `daily-news.yml` | `30 22 * * 1-5` | after the close (often starts hours late) | 15 | daily-news, then dispatches deanfi-data combine-daily-snapshots.yml |
| `analyst-trends.yml` | `0 2 * * 2-6`, `0 3 * * 2-6` | weeknights 10pm ET (DST-gated) | 5 gate + 10 | analyst-trends |
| `earnings-calendar.yml` | `45 3 * * 2-6` | weeknights | 20 | earnings-calendar |
| `earnings-surprises.yml` | `5 4 * * 2-6` | weeknights | 20 | earnings-surprises |
| `sp-growth.yml` | `15 4 * * 2-6` | weeknights | 30 | sp100growth, sp500growth |
| `options-whales.yml` | `30 16 * * 1-5`, `0 2 * * 2-6` | ~midday and ~9pm | 45 collect + 5 publish | options-whales |
| `stock-whales.yml` | `30 17 * * 1-5`, `30 2 * * 2-6` | ~12:30pm and ~9:30pm | 20 | stock-whales |
| `support-resistence.yml` | `0 9 * * 1-5`, `0 10 * * 1-5` | weekdays 5am ET (DST-gated) | 5 gate + 15 | supportresistence |
| `education-facts.yml` | `0 4 * * 4` | weekly, Wed night | 15 | education/facts.json |
| `gsc-topics.yml` | `15 4 * * 1,4` | Sun and Wed nights | 10 | education/topics.json |
| `ci.yml` | none (every push and pull request) | n/a | 15 | nothing: runs `python3 -m pytest -q`, `python3 -m pytest -q dailynews/tests` and `node --test scheduler/next-run.test.mjs` |

All workflows except `ci.yml` also accept `workflow_dispatch`. Notable inputs: `sp-growth.yml` (`universe`: both, sp100-only, sp500-only), `etf-fund-flows.yml` (`mode`: test or full; only scheduled and `full` runs publish; `tickers` for test mode, comma-separated symbols of letters, digits, `.` and `-`), `options-whales.yml` (`lookback_days`: 1–60 trading days; `test_mode`), `stock-whales.yml` (`test_mode`), `daily-news.yml` (`weekly_override` forces weekly-wrap mode, 5 catalysts). Pushes that touch the market collectors, their guards or the workflow files also trigger `market-data-intraday.yml` (main only) and `market-data-close.yml` (see each file's `push.paths`).

## Secrets and variables

Set in **Settings → Secrets and variables → Actions**.

| Secret | Used by |
|---|---|
| `DATA_REPO_TOKEN` | Every workflow: checks out and pushes to `deanfi-data`. `daily-news.yml` also uses it to dispatch combine-daily-snapshots.yml, so it needs Actions read/write on `deanfi-data`. |
| `FINNHUB_API_KEY` | `daily-news.yml`, `analyst-trends.yml`, `earnings-calendar.yml`, `earnings-surprises.yml`, `sp-growth.yml` |
| `FRED_API_KEY` | `economy-indicators.yml`, `education-facts.yml` |
| `ALPACA_API_KEY`, `ALPACA_API_SECRET` | `options-whales.yml`, `stock-whales.yml`, `support-resistence.yml` |
| `ALPHA_VANTAGE_API_KEY` | `etf-fund-flows.yml` (optional AUM fallback), `sp-growth.yml` (optional annual revenue/EPS fallback) |
| `FMP_API_KEY` | `sp-growth.yml` (optional annual revenue/EPS fallback; free tier is 250 calls/day) |
| `BLS_API_KEY`, `BEA_API_KEY` | `education-facts.yml` (BEA optional) |
| `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` | `gsc-topics.yml` (OAuth 2.0) |

Repository variable `MARKET_INTRADAY_CHAIN_DISABLED=true` stops the intraday handoff chain (see `scheduler/README.md`).

An unset optional secret reaches the collector as an empty string, and the collector skips that source. yfinance needs no key. `GITHUB_TOKEN` is read-only on this repo except for the intraday timer job, which gets `actions: write` to dispatch the next run.

## Changing or adding a workflow

- Copy an existing single-collector workflow (for example `support-resistence.yml`) and keep its structure: both checkouts into the same paths, Python 3.11, the `deanfi-data-repo` concurrency block, a `timeout-minutes`, a `data_freshness.json` update and the commit step from `docs/architecture.md`.
- Pass `workflow_dispatch` inputs to scripts through `env:` and validate them there; never write `${{ inputs.* }}` inside a `run:` script (`tests/test_workflow_inputs.py`).
- For a fixed New York time, schedule both UTC hours and gate the job with `scripts/ny_hour_gate.py` as `analyst-trends.yml` does; do not hand-toggle commented-out crons.
- Pin every third-party action to a full commit SHA with a version comment; `tests/test_workflow_action_pinning.py` enforces this and Dependabot (`.github/dependabot.yml`) groups the updates.
- `git add` only your section's paths and `data_freshness.json`, never `cache/`.
- Add the collector to `docs/collectors.md` and the workflow and its secrets to this page.
- Test with a manual `workflow_dispatch` run, then confirm the commit in `deanfi-data` and the sync-to-r2.yml run that follows.
