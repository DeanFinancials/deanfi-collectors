# Collectors

One directory per collector: a `config.yml` plus one or more `fetch_*.py` scripts. Each script writes JSON next to itself (gitignored here); the workflow copies it to the `deanfi-data` path below. Schedules are in `docs/workflows.md`.

| Directory | Data source | Workflow | Output path in deanfi-data |
|---|---|---|---|
| `advancedecline/` | yfinance (S&P 500) | `market-data-intraday.yml`, `market-data-close.yml` | `advance-decline/` |
| `majorindexes/` | yfinance | `market-data-intraday.yml`, `market-data-close.yml` | `major-indexes/` |
| `meanreversion/` | yfinance | `market-data-intraday.yml`, `market-data-close.yml` | `meanreversion/` |
| `impliedvol/` | yfinance options | `market-data-intraday.yml`, `market-data-close.yml` | `implied-volatility/` |
| `growthoutput/`, `inflationprices/`, `laboremployment/`, `moneymarkets/` | FRED | `economy-indicators.yml` | `economy-breadth/` |
| `consumercredit/` | FRED | `economy-indicators.yml` | `consumer-credit/` |
| `housingaffordability/` | FRED | `economy-indicators.yml` | `housing-affordability/` |
| `analysttrends/` | Finnhub | `analyst-trends.yml` | `analyst-trends/` |
| `earningscalendar/` | Finnhub | `earnings-calendar.yml` | `earnings-calendar/` |
| `earningssurprises/` | Finnhub | `earnings-surprises.yml` | `earnings-surprises/` |
| `spgrowth/` | SEC EDGAR, yfinance/Finnhub fallbacks | `sp-growth.yml` | `sp100growth/`, `sp500growth/` |
| `etffundflows/` | yfinance, optional Alpha Vantage | `etf-fund-flows.yml` | `etf-fund-flows/` |
| `optionswhales/` | Alpaca options | `options-whales.yml` | `options-whales/` |
| `stockwhales/` | Alpaca stocks | `stock-whales.yml` | `stock-whales/` |
| `supportresistence/` | Alpaca bars | `support-resistence.yml` | `supportresistence/` |
| `dailynews/` | Finnhub + RSS | `daily-news.yml` | `daily-news/` (news, 7-day lookback, `market_catalysts.json`) |
| `educationfacts/` | Treasury, BLS, FRED, BEA | `education-facts.yml` | `education/facts.json` |
| `gsctopics/` | Google Search Console (OAuth) | `gsc-topics.yml` | `education/topics.json` |

Collector READMEs with dataset detail: `consumercredit/README.md`, `etffundflows/README.md`, `housingaffordability/README.md`, `optionswhales/README.md`, `spgrowth/README.md`, `stockwhales/README.md`, `supportresistence/README.md`.

## Shared modules (`shared/`)

| Module | Purpose |
|---|---|
| `cache_manager.py` | `CachedDataFetcher`: parquet price cache with incremental yfinance downloads (see `docs/architecture.md`). |
| `fetch_guard.py`, `yf_retry.py`, `yf_session.py` | yfinance failure guards (see `docs/architecture.md`). |
| `spx_universe.py` | S&P 500 constituents: Wikipedia first, then `Schwab-Tickers-Combined-Final.csv` (rows whose `Index` contains `S&P 500`), then a GitHub dataset, then a hardcoded list. The single source of truth; no collector-local copies. |
| `sp100_universe.py` | S&P 100 constituents. |
| `sector_mapping.py`, `ticker_metadata.py`, `ticker_utils.py` | GICS sector lookup (backed by the Schwab CSV) and ticker normalisation (`BRK-B` ↔ `BRK.B`). |
| `redact.py` | `redact_secrets`: strips `api_key`/`apikey`/`token` values from text before it is printed or logged. |
| `fred_client.py`, `economy_indicators.py`, `economy_compute.py`, `economy_io.py` | FRED client, indicator definitions, percentile grading and JSON I/O for the economy collectors. |

`organized_etf_list.csv` at the repo root is the ETF universe for `etffundflows/`.

## Running a collector locally

```bash
pip install -r requirements.txt
export FRED_API_KEY=...          # whichever keys the collector needs (see docs/workflows.md)
cd majorindexes
python fetch_us_major.py --cache-dir ../cache   # yfinance market collectors take --cache-dir
```

Run from the collector's directory, as the workflows do. Only `shared/fred_client.py` loads a `.env` file (template: `.env.example`); other collectors read keys from the environment. `cache/` and all `*.json` outputs are gitignored.
