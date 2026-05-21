# Incident 2026-05-20 — yfinance rate limit + silent empty-write bug

## TL;DR

The `Combine Daily Snapshots` workflow in `deanfi-data` failed validation because nine `core.*` fields in `market_pulse_input.json` were empty. The empty fields traced back to upstream snapshot files in `deanfi-data/major-indexes/` and `deanfi-data/implied-volatility/` that had been overwritten with empty payloads (`indices: {}`, `sectors: {}`, `data: {}`).

Those empty payloads came from the 20:31 UTC run of the `deanfi-collectors` market-data workflow. Yahoo Finance rate-limited the runner (HTTP 429 / `YFRateLimitError`), every per-ticker fetch failed, and the collector scripts **caught the per-ticker exceptions, wrote empty JSON to disk, and reported success**. The CI then committed the empty files on top of the previous good data.

No data was permanently lost — yfinance returns full history on every call, so the next successful run repopulates `*_historical.json` from scratch.

---

## Symptom

`combine-daily-snapshots.yml` step `Validate Market Pulse input` failed:

```
FAILED: dailycombined/market_pulse_input.json
- missing core.major_index_closes
- missing core.five_session_index_returns
- missing core.five_session_breadth_lookback
- missing core.sector_leaders
- missing core.sector_laggards
- missing core.vix
- missing core.five_session_vix_lookback
- missing core.major_etf_implied_volatility
- missing core.five_session_spy_sma
- validation.is_valid must be true
Error: Process completed with exit code 1.
```

Things that were NOT missing: `core.breadth`, `core.moving_average_participation`, `core.spy_technical_levels`. (See "Why some collectors survived" below.)

## How the empty fields propagated

1. `deanfi-data/major-indexes/us_major_indices.json` had `"indices": {}` and `"data_quality": {"status": "stale", "completeness_percent": 0.0}`. Same shape for `us_sector_indices.json`, `us_growth_value_indices.json`, `international_major_indices.json`, `bond_treasury_indices.json`, `commodity_indices.json`, `implied-volatility/vix_options_snapshot.json`, `implied-volatility/major_indices_iv_snapshot.json`.
2. `combine_daily_snapshots.py` unwrapped those bodies via `pick_first_present(['data','indices','sectors'])` and stored `{}` under `data.major_indexes.*` and `data.implied_volatility.*` in `market_snapshot.json`.
3. The Market Pulse builder reads from `writer_ready` (`major_indexes_table`, `index_table_5day`, `sector_leaders`, `sector_laggards`, `volatility_summary`, `vix_table_5day`, `spy_sma_table_5day`). Because all source dicts were empty, none of those `writer_ready` keys were populated — only `breadth_table` and `technical_levels` ended up in `writer_ready`.
4. The Market Pulse core builder fell back to `or []` / `or {}` defaults, producing nine empty `core.*` containers.
5. `validate_market_pulse_core` correctly flagged those nine as missing and set `validation.is_valid = false`. The downstream validator step in CI then exited 1.

The combine workflow and validator are working correctly. The problem is entirely upstream.

## Root cause: Yahoo Finance rate limit

From `deanfi-collectors/marketdata.log` (20:29 UTC run, commit `f4cf718`):

```
[ ...big batch fetch in fetch_volume_metrics_historical.py... ]
['HAL','TYL','CBRE', ... ~250 tickers ...]: YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')

python fetch_us_major.py --cache-dir ../cache
  Fetching ^GSPC...
    ❌ Error fetching ^GSPC: Too Many Requests. Rate limited. Try after a while.
  Fetching ^DJI...
    ❌ Error fetching ^DJI:  Too Many Requests. Rate limited. Try after a while.
  Fetching ^IXIC...
    ❌ Error fetching ^IXIC: Too Many Requests. Rate limited. Try after a while.
  Fetching ^NDX...
    ❌ Error fetching ^NDX:  Too Many Requests. Rate limited. Try after a while.
  Fetching ^RUT...
    ❌ Error fetching ^RUT:  Too Many Requests. Rate limited. Try after a while.
  Fetching ^VIX...
    ❌ Error fetching ^VIX:  Too Many Requests. Rate limited. Try after a while.
✅ Saved snapshot to .../majorindexes/us_major_indices.json          ← false success
✅ Saved historical data to .../majorindexes/us_major_indices_historical.json
```

Same pattern in `fetch_sectors.py` (XLK/XLV/XLF/XLY/XLI/XLP/XLE/XLB/XLC/XLU/XLRE all 429), `fetch_growth_value.py` (^RLG/^RLV/^RUO/^RUJ/^RUA all 429), `fetch_international.py`, `fetch_bonds.py`, `fetch_commodities.py`, `fetch_vix_options.py`/`fetch_major_iv.py`, and `fetch_price_vs_ma.py` (`['SPY']: YFRateLimitError`).

Yahoo started rate-limiting during the bulk download in the breadth-collector chain that runs immediately before the per-ticker collectors. Once the rate limit was hot, every subsequent collector got 429s for every ticker.

## The actual bug to fix

The rate limit itself is annoying but expected. The real bug is in the collector scripts:

**Each `fetch_*.py` catches per-ticker exceptions, continues, and writes an empty payload while printing `✅ Saved snapshot`.** That overwrites the previous good snapshot AND the historical file. CI sees a diff, commits it, and pushes empty data downstream.

Affected scripts (each writes a `*.json` and a `*_historical.json` under its module):

- `majorindexes/fetch_us_major.py`
- `majorindexes/fetch_sectors.py`
- `majorindexes/fetch_growth_value.py`
- `majorindexes/fetch_international.py`
- `majorindexes/fetch_bonds.py`
- `majorindexes/fetch_commodities.py`
- `impliedvol/fetch_vix_options.py` (or equivalent — writes `vix_options_snapshot.json`)
- `impliedvol/fetch_major_iv.py` (or equivalent — writes `major_indices_iv_snapshot.json`)
- `meanreversion/fetch_price_vs_ma.py`

## Why some collectors survived

These ran first and either had a cache or used a single bulk download, so they finished before the rate limit kicked in:

- `advancedecline/fetch_daily_breadth.py` — `Cache age 7.2h - intraday incremental update (last 5 days)` → only 4 new rows needed → bulk-downloaded 503 symbols in one call.
- `advancedecline/fetch_ad_line_historical.py`, `fetch_ma_percentage_historical.py`, `fetch_highs_lows_historical.py` — same cache pattern.
- `advancedecline/fetch_volume_metrics_historical.py` — this is actually where the rate limit *started* (its bulk download is the source of the big `[...]: YFRateLimitError` line at 20:31:40), but it had already collected enough data via cache to write a valid file.
- `support-resistance` — older data (`last_updated: 2026-05-20T11:04:11Z`) loaded from a separate earlier run, so `core.spy_technical_levels` came through populated.

That's why `core.breadth`, `core.moving_average_participation`, and `core.spy_technical_levels` made it through while everything else came up empty.

## Fixes — in priority order

### 1. Stop overwriting good data on failure (highest priority)

In every `fetch_*.py` that loops over a ticker list, before writing the JSON file: refuse to write if too many tickers failed.

```python
if successful_fetches == 0:
    print(f"❌ All {len(symbols)} tickers failed; refusing to overwrite snapshot.")
    sys.exit(1)

# Optional partial-success threshold:
if successful_fetches < len(symbols) * 0.5:
    print(f"⚠️  Only {successful_fetches}/{len(symbols)} tickers succeeded; refusing to overwrite snapshot.")
    sys.exit(1)
```

The CI commit step is gated on the script exiting 0 — once these scripts fail loudly, the bad commit never happens, and the downstream combine workflow will use yesterday's snapshot instead of empty data.

Same treatment for the historical-file writer in each script.

### 2. Belt-and-suspenders: validate commits in CI

Before `git add` / `git commit` in `deanfi-collectors`, run a quick check: if any `*.json` snapshot's body dict (`indices`/`sectors`/`data`) is empty *and* the previous git HEAD's version had data, refuse the commit. Example:

```bash
python3 - <<'PY'
import json, subprocess, sys
files = [
  'majorindexes/us_major_indices.json',
  'majorindexes/us_sector_indices.json',
  # ...
]
for f in files:
    new = json.load(open(f))
    body_key = next((k for k in ('indices','sectors','data') if k in new), None)
    if body_key and not new.get(body_key):
        old = subprocess.check_output(['git','show',f'HEAD:{f}'], text=True)
        old = json.loads(old)
        if old.get(body_key):
            print(f'❌ {f}: about to overwrite non-empty {body_key} with empty')
            sys.exit(1)
PY
```

### 3. Mitigate the rate limit

Yahoo has been more aggressive about 429s through 2025–2026. Pick one or more:

- **Batch tickers**: replace 6× `Ticker(symbol).history()` with one `yf.download(['^GSPC','^DJI','^IXIC','^NDX','^RUT','^VIX'], …)` call. Same for sectors (1 call for all 11 XL ETFs). Cuts request count ~6–10×.
- **Per-ticker sleep**: `time.sleep(0.5–1.0)` between calls inside each fetch script.
- **Curl impersonation session**: `curl_cffi` is already a yfinance dependency; using a `requests`-compatible session with `impersonate='chrome'` materially improves success against Yahoo's bot detection.
- **Retry on 429**: catch `YFRateLimitError`, sleep 30–60s, retry once.
- **Stagger the schedule**: don't kick off every collector in the same wall-clock second. Spread them across 2–3 minutes inside the cron run (or split into separate workflows on different schedules).

### 4. Optional: tighten the market-hours gate

The damaging run was at 16:31 EDT. The collector gate is `8 <= et.hour < 17`. Yahoo data state is messy in the minutes right after the close; consider gating per-ticker collectors at `< 16:00` ET (regular session only) or running them after a `time.sleep(120)` post-close so the data has settled.

## Recovery

No revert needed:
- `*_historical.json` files: yfinance returns full history on each call → next successful run rebuilds them.
- `*.json` snapshot files: by definition replaced each session → next successful run replaces them.
- `market_pulse_input.json`: combine workflow regenerates it from the upstream files on every run.

Re-run `Combine Daily Snapshots` after the next clean collector run completes.

## Open questions / follow-ups

- Confirm the snapshot file name mismatch between the combine script and disk: `combine_daily_snapshots.py` reads `implied_vol.get('major_indices')` (loaded from a file expected to be `major_indices_snapshot.json`), but the actual file on disk is `major_indices_iv_snapshot.json`. If those don't match, `core.major_etf_implied_volatility` may stay empty even on good upstream runs. Verify the loader path in `combine_daily_snapshots.py` around line 1158 and the file pattern under `implied-volatility/`.
- Decide whether `advancedecline/fetch_volume_metrics_historical.py`'s bulk download is the primary trigger for Yahoo's rate-limit and consider splitting the S&P 500 fetch into chunks with sleeps.
