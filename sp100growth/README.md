# SP100 Growth Collector

Extracts annual (10-K) and quarterly (10-Q) financial data from SEC EDGAR for S&P 100 companies, with multi-source fallback for complete data coverage.

## What It Does

1. Fetches S&P 100 ticker list from Wikipedia (with CSV fallback)
2. Retrieves annual (10-K) and quarterly (10-Q) filings from SEC EDGAR
3. Extracts **Revenue** and **EPS (Diluted)** metrics
4. Uses fallback sources (yfinance, Alpha Vantage, Finnhub As Reported) when SEC data is incomplete
5. Calculates **Year-over-Year growth rates**, **TTM metrics**, and **CAGR**
6. Outputs a single **sp100growth.json** file

## Data Sources

### Primary Source
- **SEC EDGAR**: 10-K (annual) and 10-Q (quarterly) filings

### Annual Fallbacks (priority order)
1. **yfinance** (Yahoo Finance) - Free, no API key required
2. **Alpha Vantage** - Requires `ALPHA_VANTAGE_API_KEY`
3. **Finnhub As Reported** - Raw SEC XBRL data, excellent for banks/REITs (free)
4. **FMP** (optional) - Requires `FMP_API_KEY`, 250 calls/day limit, ~90% SP100 coverage on free tier

### Quarterly Fallbacks (priority order)
1. **yfinance** - Free quarterly financials
2. **Finnhub Standard** - Requires `FINNHUB_API_KEY`
3. **Finnhub As Reported** - Raw SEC XBRL quarterly data with YTD-to-quarterly conversion (free)

### Universe
- Wikipedia S&P 100 constituents (with CSV fallback)

## Usage

```bash
# Run with defaults (fetches S&P 100 from Wikipedia)
python fetch_sp100_growth.py

# Output to a different directory
python fetch_sp100_growth.py --output ./my_output

# Use a different config file
python fetch_sp100_growth.py --config ./custom_config.yml
```

## Output Format

Output is saved to `output/sp100growth.json`:

```json
{
  "_README": {
    "title": "S&P 100 Growth Metrics",
    "description": "Financial growth metrics extracted from SEC EDGAR filings",
    "metrics_explained": { ... }
  },
  "metadata": {
    "generated_at": "2025-12-06T23:30:00Z",
    "data_source": "SEC EDGAR + Finnhub",
    "ticker_count": 100,
    "successful_extractions": 98,
    "universe": "S&P 100"
  },
  "companies": {
    "AAPL": {
      "ticker": "AAPL",
      "sector": "Information Technology",
      "cik": "0000320193",
      "company_name": "Apple Inc.",
      "extracted_at": "2025-12-06T23:30:00Z",
      "annual_values": {
        "2024": {"revenue": 391035000000, "eps": 6.08},
        "2023": {"revenue": 383285000000, "eps": 6.13},
        "2022": {"revenue": 394328000000, "eps": 6.11},
        "2021": {"revenue": 365817000000, "eps": 5.61},
        "2020": {"revenue": 274515000000, "eps": 3.28},
        "2019": {"revenue": 260174000000, "eps": 2.97}
      },
      "quarterly_values": {
        "2024-Q3": {"revenue": 94930000000, "eps": 1.40},
        "2024-Q2": {"revenue": 85777000000, "eps": 1.53},
        "2024-Q1": {"revenue": 90753000000, "eps": 1.53},
        "2023-Q4": {"revenue": 119575000000, "eps": 2.18},
        "2023-Q3": {"revenue": 89498000000, "eps": 1.29},
        "2023-Q2": {"revenue": 81797000000, "eps": 1.26},
        "2023-Q1": {"revenue": 94836000000, "eps": 1.52},
        "2022-Q4": {"revenue": 117154000000, "eps": 1.88}
      },
      "growth": {
        "revenue_yoy": {"2024": -0.028, "2023": 0.078},
        "eps_yoy": {"2024": -0.003, "2023": 0.041},
        "ttm": {
          "revenue": 383285000000,
          "eps_diluted": 6.11,
          "revenue_yoy": 0.02,
          "eps_yoy": 0.05,
          "as_of_quarter": "2024-09-28",
          "source": "sec"
        },
        "revenue_cagr_3yr": 0.024,
        "eps_cagr_3yr": 0.019,
        "revenue_cagr_5yr": 0.08,
        "eps_cagr_5yr": 0.12
      },
      "errors": []
    }
  }
}
```

## Metrics Explained

| Metric | Description | Format |
|--------|-------------|--------|
| `sector` | GICS sector classification | String (e.g., 'Information Technology') |
| `annual_values` | Actual annual revenue and EPS by year | Object keyed by year (e.g., '2024') |
| `annual_values[year].revenue` | Annual revenue | USD |
| `annual_values[year].eps` | Annual diluted EPS | USD per share |
| `quarterly_values` | Actual quarterly revenue and EPS | Object keyed by quarter (e.g., '2024-Q3') |
| `quarterly_values[qtr].revenue` | Quarterly revenue | USD |
| `quarterly_values[qtr].eps` | Quarterly diluted EPS | USD per share |
| `revenue_yoy` | Year-over-year revenue growth | Decimal (0.05 = 5%) |
| `eps_yoy` | Year-over-year EPS growth | Decimal |
| `ttm.revenue` | Trailing 12 months revenue | USD |
| `ttm.eps_diluted` | Trailing 12 months EPS | USD per share |
| `ttm.revenue_yoy` | TTM vs prior TTM revenue growth | Decimal |
| `ttm.eps_yoy` | TTM vs prior TTM EPS growth | Decimal |
| `revenue_cagr_3yr` | 3-year revenue CAGR | Decimal |
| `eps_cagr_3yr` | 3-year EPS CAGR | Decimal |
| `revenue_cagr_5yr` | 5-year revenue CAGR | Decimal |
| `eps_cagr_5yr` | 5-year EPS CAGR | Decimal |

## Configuration

Edit `config.yml` to customize:

- **SEC user agent**: Required - your email for SEC rate limiting
- **Years to fetch**: Number of annual periods (default: 6)
- **Quarters to fetch**: Number of quarterly periods (default: 8)
- **Concepts**: XBRL concepts to extract (with fallback options)
- **Output settings**: Directory and filename

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FINNHUB_API_KEY` | Finnhub API key for quarterly fallback | Optional |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API key for annual fallback | Optional |
| `FMP_API_KEY` | FMP API key (disabled by default) | Optional |

Note: yfinance requires no API key and is the primary fallback source for both annual and quarterly data.

## Fallback Status

When fallback data is used, the `*_validation` field indicates the confidence level:

| Status | Description |
|--------|-------------|
| `validated` | Multiple sources agree within 5% |
| `single_source` | Only one fallback source had data |
| `discrepancy` | Sources disagree >5% (uses primary source) |

## Files

| File | Description |
|------|-------------|
| `fetch_sp100_growth.py` | Main extraction script |
| `config.yml` | Configuration file |

The S&P 100 universe is fetched from `shared/sp100_universe.py`.

## Dependencies

- `secedgar` - SEC EDGAR API client
- `yfinance` - Yahoo Finance API for fallback data
- `pandas` - Data handling
- `pyyaml` - Config parsing
- `requests` - HTTP requests

These are included in the project's `requirements.txt`.

## Fallback Coverage

The multi-source fallback ensures **100% CAGR data coverage** for all S&P 100 companies:

| Ticker Type | Issue | Solution |
|-------------|-------|----------|
| Banks (GS, WFC, MS, USB) | Use different revenue concepts | Finnhub As Reported (InterestIncome + NoninterestIncome) |
| REITs (SPG) | Use lease income instead of revenue | Finnhub As Reported (OperatingLeaseLeaseIncome) |
| Asset managers (BLK) | Missing historical data in standardized APIs | Finnhub As Reported (raw SEC XBRL) |
| Non-calendar FY (NVDA) | SEC data gaps | yfinance fills missing years |
| Payment processors (V) | Missing quarterly EPS | yfinance quarterly fallback |
| Holding companies (BRK-B) | Non-standard EPS | Finnhub As Reported calculates from Net Income/Shares |
| Large tech (GOOGL) | SEC quarterly gaps | yfinance quarterly fallback |

### CAGR Coverage
- **Revenue CAGR 5yr**: 100% coverage (0 nulls)
- **EPS CAGR 5yr**: 100% coverage (0 nulls)
- **Revenue CAGR 3yr**: 100% coverage (0 nulls)
- **EPS CAGR 3yr**: 100% coverage (0 nulls)

### TTM Coverage
TTM YoY requires 8 consecutive quarters of complete data:
- **ttm.revenue_yoy**: 100% coverage (0 nulls)
- **ttm.eps_yoy**: 99% coverage (1 null - BRK-B due to Q4 2024 EPS unavailable)

Note: BRK-B's TTM EPS null is a fundamental data limitation - Berkshire doesn't file Q4 10-Q reports, and Q4 2024 EPS is not available in yfinance.

## Schedule

Runs nightly at 11:15pm Eastern (04:15 UTC) via GitHub Actions, 15 minutes after the analyst-trends and earnings collectors.

## Special Ticker Handling

- **BRK.B** → **BRK-B**: Wikipedia uses BRK.B but SEC EDGAR uses BRK-B
- **GOOGL vs GOOG**: Deduplicates to GOOGL (Class A shares)
