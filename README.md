# DeanFi Collectors

**Automated market intelligence pipeline for modern developers**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Data Updates](https://img.shields.io/badge/updates-every%2010min-brightgreen)](https://github.com/GibsonNeo/deanfi-data)

Python-based data collectors that fetch earnings, news, analyst trends, and market breadth indicators every 10 minutes during market hours. Powers the [deanfi-data](https://github.com/GibsonNeo/deanfi-data) public API and [DeanFinancials.com](https://deanfinancials.com).

## 📊 Data Collectors

| Collector | Description | Update Frequency | Data Source |
|-----------|-------------|------------------|-------------|
| **Daily News** | Top market news + sector breakdowns | Manual only | Finnhub |
| **Analyst Trends** | Recommendation changes (buy/hold/sell) | Nightly (11pm ET) | Finnhub |
| **Earnings Calendar** | Upcoming earnings releases + estimates | Nightly (11pm ET) | Finnhub |
| **Earnings Surprises** | Historical EPS vs estimates | Nightly (11pm ET) | Finnhub |
| **SP100 Growth** | Revenue & EPS growth metrics for S&P 100 | Nightly (11:15pm ET) | SEC EDGAR + fallback¹ |
| **ETF Fund Flows** | Daily AUM + implied flow inputs (NAV + close return bases) | Nightly (after close) | Yahoo Finance (yfinance) + optional fallbacks |
| **Advance/Decline** | Market breadth indicators (with caching) | Every 10 min (market hours) | Yahoo Finance |
| **Major Indexes** | S&P 500, Dow, Nasdaq tracking (with caching) | Every 10 min (market hours) | Yahoo Finance |
| **Implied Volatility** | VIX and options volatility | Every 10 min (market hours) | Yahoo Finance |
| **Growth & Output** | GDP, industrial production, capacity utilization | Daily (12pm ET Mon-Fri) | FRED |
| **Inflation & Prices** | CPI, PCE, PPI, breakeven inflation | Daily (12pm ET Mon-Fri) | FRED |
| **Labor & Employment** | Unemployment, payrolls, wages, job openings | Daily (12pm ET Mon-Fri) | FRED |
| **Money & Markets** | Fed funds, Treasuries, yield spread, M2 | Daily (12pm ET Mon-Fri) | FRED |
| **Consumer & Credit** | Sentiment, retail sales, saving rate, revolving/nonrevolving credit | Daily (12pm ET Mon-Fri) | FRED |
| **Housing & Affordability** | Housing activity, home prices, mortgage rates, debt service, affordability | Daily (12pm ET Mon-Fri) | FRED |
| **Mean Reversion** | Price vs MA metrics + MA spreads with z-scores | Every 10 min (market hours) | Yahoo Finance |
| **Options Whales** | Large OTM options trades with sweep detection | Twice daily (12pm & 9pm ET) | Alpaca Markets |
| **Stock Whales** | Large stock trades with dark pool detection | Twice daily (12pm & 9pm ET) | Alpaca Markets |

¹ **SP100 Growth Data Sources**: Primary source is SEC EDGAR XBRL filings. When SEC data is unavailable (e.g., some financial sector companies, companies with non-standard filings), uses 3-source consensus validation: yfinance, Alpha Vantage, and FMP (Financial Modeling Prep). If 2+ sources agree within 5%, the value is marked "validated". If all sources differ, the average is used and marked "discrepancy".

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Free Finnhub API key: [Register here](https://finnhub.io/register)
- Free FRED API key: [Register here](https://fred.stlouisfed.org/docs/api/api_key.html)
- (Optional) GitHub Personal Access Token for workflow testing

### Installation

```bash
# Clone the repository
git clone https://github.com/GibsonNeo/deanfi-collectors.git
cd deanfi-collectors

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your FINNHUB_API_KEY and FRED_API_KEY
```

### Running Collectors Locally

```bash
# Fetch daily news
cd dailynews
python fetch_top_news.py

# Check output
cat top_news.json | head -50

# Fetch sector news
python fetch_sector_news.py

# Fetch analyst trends
cd ../analysttrends
python fetch_recommendation_trends.py

# Fetch earnings calendar
cd ../earningscalendar
python fetch_earnings_calendar.py

# Fetch market breadth with caching
cd ../advancedecline
python fetch_daily_breadth.py --cache-dir ./cache

# Fetch major indexes with caching
cd ../majorindexes
python fetch_us_major.py --cache-dir ./cache

# Fetch mean reversion indicators with caching
cd ../meanreversion
python fetch_price_vs_ma.py --cache-dir ./cache
python fetch_ma_spreads.py --cache-dir ./cache

# Fetch economy breadth indicators
cd ../growthoutput
python fetch_growth_output.py

cd ../inflationprices
python fetch_inflation_prices.py

cd ../laboremployment
python fetch_labor_employment.py

cd ../moneymarkets
python fetch_money_markets.py
```

## 📁 Project Structure

```
deanfi-collectors/
├── .github/workflows/       # GitHub Actions automation
├── shared/                  # Shared utilities
│   ├── spx_universe.py     # S&P 500 ticker fetcher
│   ├── sp100_universe.py   # S&P 100 ticker fetcher
│   ├── sector_mapping.py   # Sector classification (with ticker normalization)
│   ├── ticker_utils.py     # Ticker normalization helpers
│   ├── ticker_metadata.py  # Schwab CSV-backed sector/industry lookup
│   ├── cache_manager.py    # Intelligent caching with incremental updates
│   ├── fred_client.py      # FRED API client for economic data
│   ├── economy_indicators.py  # Economic indicator definitions
│   ├── economy_compute.py  # Economic calculations & grading
│   └── economy_io.py       # Config loading & JSON saving
├── dailynews/              # Market & sector news
│   ├── fetch_top_news.py
│   ├── fetch_sector_news.py
│   ├── finnhub_client.py
│   └── config.yml
├── analysttrends/          # Analyst recommendations
│   ├── fetch_recommendation_trends.py
│   ├── analyze_ticker_trends.py
│   ├── aggregate_by_sector.py
│   └── config.yml
├── earningscalendar/       # Earnings dates & estimates
│   ├── fetch_earnings_calendar.py
│   └── config.yml
├── earningssurprises/      # Historical EPS surprises
│   ├── fetch_earnings_surprises.py
│   └── config.yml
├── advancedecline/         # Market breadth
│   ├── fetch_daily_breadth.py
│   ├── fetch_ad_line_historical.py
│   └── config.yml
├── majorindexes/           # Index tracking
├── impliedvol/             # Volatility data
├── meanreversion/          # Price vs MA + MA spread metrics
│   ├── fetch_price_vs_ma.py
│   ├── fetch_ma_spreads.py
│   ├── utils.py
│   └── config.yml
├── growthoutput/           # GDP & economic growth indicators
│   ├── fetch_growth_output.py
│   └── config.yml
├── inflationprices/        # CPI, PCE, PPI inflation metrics
│   ├── fetch_inflation_prices.py
│   └── config.yml
├── laboremployment/        # Jobs, unemployment, wages
│   ├── fetch_labor_employment.py
│   └── config.yml
├── moneymarkets/           # Interest rates, yield curve, M2
│   ├── fetch_money_markets.py
│   └── config.yml
├── sp100growth/            # S&P 100 revenue & EPS growth
│   ├── fetch_sp100_growth.py
│   └── config.yml
├── etffundflows/           # ETF AUM + implied fund flows (monthly JSON)
│   ├── fetch_etf_fund_flows.py
│   └── config.yml
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
└── README.md              # This file
```

## ⚙️ GitHub Actions Automation

This repository uses GitHub Actions to automatically collect data and publish to [deanfi-data](https://github.com/GibsonNeo/deanfi-data).

### Schedule

**High-Frequency (Every 10 min during market hours):**
- Consolidated `market-data-10min.yml` workflow (breadth, indexes, implied vol, mean reversion)
- Runs 8:05am–4:55pm Eastern with a 5-minute buffer for reliability
- EST cron: `5-55/10 13-21 * * 1-5` (EDT variant: `5-55/10 12-20 * * 1-5`)
- **Runtime:** ~3-4 min/run, ~90 hours/month

**Twice Daily (Market open & close):**
- Daily news (currently paused; manual runs only)
- **Runtime:** ~2 min/run, ~1.5 hours/month

**Weekly (Sunday 12:00pm ET):**
- Analyst recommendations
- Earnings calendar & surprises
- **Runtime:** ~5 min/run, ~0.5 hours/month

**Daily (Weekdays 12:00pm ET):**
- Economic indicators (Growth & Output, Inflation & Prices, Labor & Employment, Money & Markets)
- **Runtime:** ~3 min/run, ~15 hours/month

**Total:** ~106 hours/month (well under GitHub's 2,000 hour free tier)

### Setup GitHub Actions

1. **Create secrets** in repository settings:
   - `FINNHUB_API_KEY` - Your Finnhub API key
   - `FRED_API_KEY` - Your FRED API key
   - `ALPHA_VANTAGE_API_KEY` - Your Alpha Vantage API key (for SP100 Growth fallback)
   - `FMP_API_KEY` - Your Financial Modeling Prep API key (for SP100 Growth tiebreaker)
   - `DATA_REPO_TOKEN` - Personal access token with `repo` scope

2. **Enable Actions** in Settings → Actions → General

3. **Workflows run automatically** on schedule or manually via "Run workflow"

## 🔧 Configuration

Each collector has a `config.yml` file with settings:

```yaml
# Example: dailynews/config.yml
api:
  finnhub_api_key: "${FINNHUB_API_KEY}"  # Reads from environment
  base_url: "https://finnhub.io/api/v1"

news:
  lookback_days: 7
  max_articles: 100
```

**All API keys are read from environment variables** - never hardcoded!

## 💡 Key Features

### Intelligent Caching
- **Incremental downloads:** Only fetches new data since last run
- **Cache-age aware:** 
  - <24h old: 5-day incremental update
  - 24-168h old: 10-day incremental update
  - >168h old: Full weekly rebuild
- **Active collectors:** Market breadth (advancedecline) and Major indexes (majorindexes)
- **Storage:** Cache persists in deanfi-data repo across workflow runs
- **Saves ~85% of API calls and GitHub Actions time**

### Rate Limiting
- Built-in rate limit handling for all APIs
- Sliding window algorithm to stay within limits
- Automatic retry with exponential backoff
- Detailed progress reporting

### Error Handling
- Graceful degradation on API failures
- Comprehensive logging to stderr
- Validation of API responses
- Summary statistics on completion

### Data Quality
- Deduplication of tickers (handles GOOGL/GOOG, BRK.A/BRK.B)
- Timestamp tracking for freshness
- JSON output validation
- Metadata included in all outputs

## 📖 Usage Examples

### Fetching Daily News

```python
from dailynews.finnhub_client import FinnhubClient
import os

api_key = os.getenv('FINNHUB_API_KEY')
client = FinnhubClient(api_key=api_key)

# Fetch top news
news = client.fetch_company_news('AAPL', from_date='2025-11-10', to_date='2025-11-17')
for article in news:
    print(f"{article['headline']} - {article['source']}")
```

### Using Cached Data

```python
from shared.cache_manager import CachedDataFetcher

# Initialize cached fetcher
fetcher = CachedDataFetcher(cache_dir='./cache')

# Download with intelligent caching
data = fetcher.fetch_prices(
    tickers=['AAPL', 'MSFT', 'GOOGL'],
    period='2y',
    cache_name='my_data'
)

# Cache automatically handles:
# - Incremental updates based on age
# - Parquet storage (10x faster than CSV)
# - Self-healing if corrupted
```

## 🤝 Contributing

We welcome contributions! Whether it's:

- 🐛 Bug fixes
- ✨ New data collectors
- 📚 Documentation improvements
- 🎨 Code quality enhancements

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Guide

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-collector`
3. Make your changes and test locally
4. Commit using conventional commits: `git commit -m "feat: add crypto data collector"`
5. Push and create a Pull Request

## 📊 Output Formats

All collectors output clean JSON with consistent structure:

```json
{
  "metadata": {
    "generated_at": "2025-11-17T14:30:00Z",
    "source": "Finnhub API",
    "total_items": 100
  },
  "data": [
    {
      "symbol": "AAPL",
      "headline": "Apple announces new product",
      "datetime": 1700236800,
      "source": "Bloomberg"
    }
  ]
}
```

## 🔒 Security

- **Never commit API keys** - Use environment variables only
- **Review `.gitignore`** - Ensures `.env` files are excluded
- **GitHub secrets** - Stay private even in public repos
- **Automatic redaction** - Secrets are masked in workflow logs

## 📈 Data Access

All collected data is published to the public [deanfi-data](https://github.com/GibsonNeo/deanfi-data) repository:

```javascript
// Fetch latest news
const url = 'https://raw.githubusercontent.com/GibsonNeo/deanfi-data/main/daily-news/top_news.json';
const response = await fetch(url);
const news = await response.json();
```

See the data repository for complete API documentation and usage examples.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Data Sources:**
  - [Finnhub.io](https://finnhub.io) - Financial data API
  - [Yahoo Finance](https://finance.yahoo.com) - Market data via yfinance
- **Powered by:** GitHub Actions for automation
- **Built with:** Python, pandas, requests

## 📞 Contact & Support

- **Website:** [DeanFinancials.com](https://deanfinancials.com)
- **Issues:** [GitHub Issues](https://github.com/GibsonNeo/deanfi-collectors/issues)
- **Discussions:** [GitHub Discussions](https://github.com/GibsonNeo/deanfi-collectors/discussions)

---

Made with ❤️ by the Dean Financials team. Star ⭐ if you find this useful!
