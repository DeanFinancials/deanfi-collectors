# AGENTS.md

Single entry point for coding agents in `deanfi-collectors`. This file is the table of contents: read it, then open only the doc the task needs (see the docs map). `README.md` is for humans.

## Project snapshot

- Python 3.11 data collectors, one directory per data domain (a config.yml plus `fetch_*.py` scripts), with shared helpers in `shared/`.
- Each GitHub Actions workflow in `.github/workflows/` runs collectors and commits their JSON to the sibling repo deanfi-data, the source of truth for website dashboard data.
- Sources: Yahoo Finance (yfinance), FRED, Finnhub, Alpaca, SEC EDGAR, RSS, Google Search Console.
- Intraday market data runs every 15 minutes in market hours through a self-dispatching chain (`scheduler/`); everything else is cron.
- Tests: pytest under `tests/` (plus `dailynews/tests/`) and a Node test for the scheduler.

## Commands

- Install: `pip install -r requirements.txt`
- Tests: `python3 -m pytest -q` (one file: `python3 -m pytest -q tests/test_fetch_guard.py`)
- Daily-news tests (outside the default path): `python3 -m pytest -q dailynews/tests`
- Scheduler tests: `node --test scheduler/next-run.test.mjs`
- Run a collector: `cd majorindexes && python fetch_us_major.py --cache-dir ../cache` (export the API keys it needs first; outputs land next to the script and are gitignored)
- Validate market snapshots against HEAD (from a deanfi-data checkout): `python ../scripts/validate_snapshots.py`

## Invariants

Break these only when the task explicitly changes them.

- Every job that pushes to deanfi-data uses concurrency group `deanfi-data-repo` with `queue: max` and `cancel-in-progress: false`, and sets `timeout-minutes`. Jobs that only wait or collect use their own group.
- Commit pattern: collect → copy into the data-cache checkout of deanfi-data → update data_freshness.json → `git add` only the workflow's own sections → `git commit` → `git pull --rebase origin main` → `git push`. The intraday market workflow publishes through `scripts/publish_market_data.py` instead.
- The yfinance price cache (parquet) persists through the actions/cache action only. Never commit it or add cache/ to a `git add` line.
- Validators reject bad data before it replaces good data: collectors exit non-zero on zero successful tickers (`shared/fetch_guard.py`), and `scripts/validate_snapshots.py` blocks empty, null-price or malformed market snapshots. Never write an empty payload over a good file.
- Every third-party action is pinned to a full commit SHA with a version comment (`tests/test_workflow_action_pinning.py`).
- Secrets come from GitHub Secrets or environment variables only; never hardcode or log them.
- Cloudflare R2 is downstream: deanfi-data's sync-to-r2 workflow mirrors it. Nothing here writes to R2 or reads data back from it.
- Each rule has one home. Link to it instead of copying it into another doc.

## Docs map

| Doc | Read when |
|-----|-----------|
| `docs/architecture.md` | You change a workflow's steps, the commit/publish path, caching, the yfinance guards or validators, or debug stale data on the website. |
| `docs/collectors.md` | You need which collector produces which deanfi-data path, its source, the `shared/` modules, or how to run one locally. |
| `docs/workflows.md` | You change a schedule, timeout, secret or trigger, or add a workflow. |
| `docs/context.md` | You meet a domain term (section, freshness, Market Pulse Input, catalyst, handoff). |
| `docs/requirements.md` | You need toolchain versions, source rate limits, collector coding rules, or the add-a-collector checklist. |
| `scheduler/README.md` | You touch `.github/workflows/market-data-intraday.yml` handoffs, `scheduler/next-run.mjs`, or the chain disable switch. |
| `.github/CONTRIBUTING.md` | You need the PR and commit-message conventions. |
| `SECURITY.md` | You handle a vulnerability report. |

Per-collector READMEs (for example `spgrowth/README.md`, `optionswhales/README.md`) explain a dataset's methodology and output fields; `docs/collectors.md` lists them all.

## Definition of done

- Make the smallest change that solves the task and follows the existing patterns. No surprise dependency churn or output-shape changes; the website reads these files.
- Scoped change: the narrowest relevant test passes (`python3 -m pytest -q <path>`).
- Workflow or shared-module change: `python3 -m pytest -q` passes, plus the scheduler Node test if `scheduler/` changed.
- Docs-only change: every path you touched resolves (`tests/test_doc_links.py` checks the paths in this file).
- If the change affects a schedule, secret, output path, publish step or guard, update the doc that owns it in the same change.
