# AGENTS.md — deanfi-collectors

Canonical instruction file for coding agents working in this repo.

## What This Repo Does

Runs Python data collectors as GitHub Actions workflows. Each collector fetches
financial data from an external API (Yahoo Finance/yfinance, Finnhub, Alpaca,
FRED) and writes JSON files to disk. Workflows then commit those files to the
`deanfi-data` GitHub repository, which is the single source of truth for all
dashboard data on the website.

## Data Flow (end-to-end)

```
deanfi-collectors (this repo)
  └─ GitHub Actions workflow
       └─ Python script → writes JSON to disk
            └─ git push → deanfi-data repo (GitHub)
                  └─ sync-to-r2.yml (triggers on every push with JSON changes)
                        └─ Cloudflare R2 bucket (https://r2.deanfi.com)
                              └─ fetchFromR2 utility → useR2Data hook → React dashboard
```

**Key facts for agents:**
- Data IS served from the R2 bucket at `https://r2.deanfi.com`. The `useR2Data`
  hook name is accurate — it fetches from R2 via `src/utils/r2-fetch.ts`.
- The Cloudflare Pages Function proxy at `functions/data/[[path]].ts` exists in
  the website but is NOT the active data path for dashboards. Do not route new
  dashboard data through it.
- The R2 sync (`deanfi-data/.github/workflows/sync-to-r2.yml`) is a second
  failure point. If it fails, data is in GitHub but not in R2, and the website
  sees stale data even if collectors ran fine. Check `sync-to-r2.yml` run history
  in `deanfi-data` when debugging website staleness.
- `data_freshness.json` written to `deanfi-data` is automatically synced to R2
  by `sync-to-r2.yml`. The website fetches it from
  `https://r2.deanfi.com/data_freshness.json`.
- Worst-case latency from collector run to user seeing data: ~16 minutes
  (10-min collection cycle + ~1 min R2 sync + 5-min React Query staleTime).

## Repo Layout

```
.github/workflows/    GitHub Actions automation (one file per data domain)
shared/               Shared Python utilities (caching, FRED client, universes)
<domain>/             One directory per collector (config.yml + fetch_*.py)
deanfi-data/          (not in this repo — the sibling data repo on GitHub)
```

## Workflow Architecture

- All workflows share concurrency group `deanfi-data-repo` with
  `cancel-in-progress: false`. This serialises pushes to `deanfi-data` and
  prevents git conflicts.
- The commit pattern is: collect → `git add` → `git commit` → `git pull --rebase`
  → `git push`. The rebase step handles any external pushes that happened during
  the run.
- Price cache (parquet files) is stored via `actions/cache`, not committed to
  `deanfi-data`. Do not add `cache/` back to `git add` lines.

## Key Files

- `implementation-plan.md` — active reliability improvement checklist
- `CONTEXT.md` — domain glossary and reliability decisions
- `requirements.txt` — Python dependencies
- `.env.example` — required environment variables

## Collectors Quick Reference

| Directory | Data Source | Schedule | Output → deanfi-data path |
|---|---|---|---|
| `advancedecline/` | yfinance | every 10 min (market hrs) | `advance-decline/` |
| `majorindexes/` | yfinance | every 10 min (market hrs) | `major-indexes/` |
| `meanreversion/` | yfinance | every 10 min (market hrs) | `meanreversion/` |
| `impliedvol/` | yfinance | every 10 min (market hrs) | `implied-volatility/` |
| `growthoutput/` | FRED | daily weekdays | `economy-breadth/` |
| `inflationprices/` | FRED | daily weekdays | `economy-breadth/` |
| `laboremployment/` | FRED | daily weekdays | `economy-breadth/` |
| `moneymarkets/` | FRED | daily weekdays | `economy-breadth/` |
| `consumercredit/` | FRED | daily weekdays | `consumer-credit/` |
| `housingaffordability/` | FRED | daily weekdays | `housing-affordability/` |
| `earningscalendar/` | Finnhub | nightly | `earnings-calendar/` |
| `earningssurprises/` | Finnhub | nightly | `earnings-surprises/` |
| `analysttrends/` | Finnhub | nightly | `analyst-trends/` |
| `spgrowth/` | SEC EDGAR + fallbacks | nightly | `sp100growth/`, `sp500growth/` |
| `optionswhales/` | Alpaca | twice daily | `options-whales/` |
| `stockwhales/` | Alpaca | twice daily | `stock-whales/` |
| `etffundflows/` | yfinance | daily after close | `etf-fund-flows/` |
| `supportresistence/` | Alpaca | daily 5am ET | `supportresistence/` |
| `dailynews/` | Finnhub | manual only | `daily-news/` |
