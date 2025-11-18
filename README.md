# DeanFi Collectors

**Automated market intelligence pipeline for modern developers**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Data Updates](https://img.shields.io/badge/updates-every%2015min-brightgreen)](https://github.com/GibsonNeo/deanfi-data)

Python-based data collectors that fetch earnings, news, analyst trends, and market breadth indicators every 15 minutes during market hours. Powers the [deanfi-data](https://github.com/GibsonNeo/deanfi-data) public API and [DeanFinancials.com](https://deanfinancials.com).

## 📊 Data Collectors

| Collector | Description | Update Frequency | Data Source |
|-----------|-------------|------------------|-------------|
| **Daily News** | Top market news + sector breakdowns | Twice daily (9:30am & 4pm ET) | Finnhub |
| **Analyst Trends** | Recommendation changes (buy/hold/sell) | Weekly (Sunday 12pm ET) | Finnhub |
| **Earnings Calendar** | Upcoming earnings releases + estimates | Weekly (Sunday 12pm ET) | Finnhub |
| **Earnings Surprises** | Historical EPS vs estimates | Weekly (Sunday 12pm ET) | Finnhub |
| **Advance/Decline** | Market breadth indicators (with caching) | Every 15 min (market hours) | Yahoo Finance |
| **Major Indexes** | S&P 500, Dow, Nasdaq tracking (with caching) | Every 15 min (market hours) | Yahoo Finance |
| **Implied Volatility** | VIX and options volatility | Every 15 min (market hours) | Yahoo Finance |

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Free Finnhub API key: [Register here](https://finnhub.io/register)
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
# Edit .env and add your FINNHUB_API_KEY
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
```

## 📁 Project Structure

```
deanfi-collectors/
├── .github/workflows/       # GitHub Actions automation
├── shared/                  # Shared utilities
│   ├── spx_universe.py     # S&P 500 ticker fetcher
│   └── cache_manager.py    # Intelligent caching with incremental updates
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
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
└── README.md              # This file
```

## ⚙️ GitHub Actions Automation

This repository uses GitHub Actions to automatically collect data and publish to [deanfi-data](https://github.com/GibsonNeo/deanfi-data).

### Schedule

**High-Frequency (Every 15 min during market hours):**
- Market breadth (advance/decline indicators)
- Major indexes (S&P 500, Dow, Nasdaq, sectors)
- Implied volatility (VIX, options data)
- **Runtime:** ~2-3 min/run, ~70 hours/month

**Twice Daily (Market open & close):**
- Daily news (9:30am ET and 4:00pm ET)
- **Runtime:** ~2 min/run, ~1.5 hours/month

**Weekly (Sunday 12:00pm ET):**
- Analyst recommendations
- Earnings calendar & surprises
- **Runtime:** ~5 min/run, ~0.5 hours/month

**Total:** ~72 hours/month (well under GitHub's 2,000 hour free tier)

### Setup GitHub Actions

1. **Create secrets** in repository settings:
   - `FINNHUB_API_KEY` - Your Finnhub API key
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
