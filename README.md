# DeanFi Collectors

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Python data collectors, run on GitHub Actions, that fetch market, economic, earnings, news and options data and publish JSON to the [deanfi-data](https://github.com/DeanFinancials/deanfi-data) repository. From there the data is mirrored to Cloudflare R2 and drives the dashboards on [deanfi.com](https://deanfi.com).

## What it collects

- **Intraday market data** every 15 minutes in US market hours: advance/decline breadth, major and sector indexes, mean reversion, implied volatility (Yahoo Finance).
- **Economy** twice each weekday: growth, inflation, labor, money markets, consumer credit, housing (FRED).
- **Nightly**: analyst trends, earnings calendar and surprises (Finnhub), S&P 100/500 revenue and EPS growth (SEC EDGAR).
- **Daily**: ETF fund flows, market news and ranked market catalysts, support/resistance levels, options and stock whale trades (Alpaca).
- **Weekly**: education facts (Treasury, BLS, FRED, BEA) and search topics (Google Search Console).

The full list with sources, workflows and output paths is in [docs/collectors.md](docs/collectors.md).

## Quick start

```bash
git clone https://github.com/DeanFinancials/deanfi-collectors.git
cd deanfi-collectors
pip install -r requirements.txt          # Python 3.11
python3 -m pytest -q                      # tests

cd majorindexes
python fetch_us_major.py --cache-dir ../cache   # yfinance collectors need no API key
```

Other collectors need API keys in the environment; see [docs/workflows.md](docs/workflows.md#secrets-and-variables).

## Docs

- [docs/architecture.md](docs/architecture.md): data flow, workflow anatomy, caching and data-quality guards
- [docs/collectors.md](docs/collectors.md): every collector, its source and output, and how to run one
- [docs/workflows.md](docs/workflows.md): schedules, secrets and how to add a workflow
- [docs/context.md](docs/context.md): glossary
- [docs/requirements.md](docs/requirements.md): toolchain and engineering rules
- [scheduler/README.md](scheduler/README.md): the self-dispatching intraday schedule
- [AGENTS.md](AGENTS.md): entry point for coding agents
- [Contributing](.github/CONTRIBUTING.md) · [Security policy](SECURITY.md)

## License

MIT; see [LICENSE](LICENSE).
