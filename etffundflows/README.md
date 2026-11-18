# ETF Fund Flows Collector

This collector derives **daily ETF fund flows** for the tickers in `organized_etf_list.csv` (repo root). `etf-fund-flows.yml` runs it each weekday after the close.

## What it does
For each ETF ticker, once per trading day (after market close):
- Fetches **AUM** and **NAV** primarily from Yahoo Finance via `yfinance` (`Ticker.info`: `totalAssets`, `navPrice`)
- Optionally falls back to:
	- **Alpha Vantage** `ETF_PROFILE` (`net_assets`, AUM-only)
- Fetches **daily closes** from Yahoo Finance via `yfinance` (batched)
- Computes estimated flows using the industry-standard derived approach:

$$
\text{Flow}_t = AUM_t - (AUM_{t-1} \times R_t)
$$

Where:
- Primary return factor (recommended): $R_t = NAV_t / NAV_{t-1}$
- Secondary return factor: $R_t = Close_t / Close_{t-1}$

Outputs are written as **monthly JSON** files and copied to the `deanfi-data` repo by the workflow.

### Zero-success guard
The workflow seeds `output/` with the published month files and the script upserts the session into them in place. Before writing, the script calls `assert_enough_succeeded` (`shared/fetch_guard.py`, rule in `docs/architecture.md`): if no ticker got an AUM value for the session, it exits 1 and writes nothing, so the last good files stay. A ticker counts as succeeded when its point has AUM, the input every flow needs. Null flows do not count against it: a first run with nothing seeded, or a ticker with no prior point, records `missing_prior_day` and still succeeds.

## Configuration
See `config.yml`.

## Running locally
From repo root:

```bash
cd etffundflows
python fetch_etf_fund_flows.py --config ./config.yml --tickers SPY,VOO,XLV
```

Notes:
- By default, the collector can run with **no paid API keys** (yfinance-only), but AUM/NAV fields may be missing for some ETFs.
- Optional env vars (only used if enabled by `aum_nav.source_order` in `config.yml`):
	- `ALPHA_VANTAGE_API_KEY`
- Use `--tickers` or `--limit` for testing to keep optional fallback calls low.
