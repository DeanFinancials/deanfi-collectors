# S&P Growth Collector

Unified collector that extracts annual (10-K) and quarterly (10-Q) financial data from SEC EDGAR for S&P 500 companies. Generates both sp100growth.json (S&P 100 subset) and sp500growth.json (full S&P 500) from a single run.

## What It Does

1. Fetches S&P 500 ticker list from Wikipedia (via `spx_universe.py`)
2. Fetches S&P 100 ticker list for filtering (via `sp100_universe.py`)
3. Retrieves annual (10-K) and quarterly (10-Q) filings from SEC EDGAR
4. Extracts **Revenue** and **EPS (Diluted)** metrics
5. Uses fallback sources (yfinance, Alpha Vantage, Finnhub) when SEC data is incomplete
6. Calculates **Year-over-Year growth rates**, **TTM metrics**, and **CAGR**
7. Outputs both **sp100growth.json** and **sp500growth.json** from a single run

## Efficiency

This unified collector processes the full S&P 500 once and generates both output files:
- No duplicate API calls for S&P 100 companies
- Single pass through SEC EDGAR data
- S&P 100 output is filtered from the full dataset

## Data Sources

### Primary Source
- **SEC EDGAR**: 10-K (annual) and 10-Q (quarterly) filings

### Annual Fallbacks (priority order)
1. **yfinance** (Yahoo Finance) - Free, no API key required
2. **Alpha Vantage** - Requires `ALPHA_VANTAGE_API_KEY`
3. **Finnhub As Reported** - Raw SEC XBRL data, excellent for banks/REITs (free)

### Quarterly Fallbacks (priority order)
1. **yfinance** - Free quarterly financials
2. **Finnhub Standard** - Requires `FINNHUB_API_KEY`
3. **Finnhub As Reported** - Raw SEC XBRL quarterly data with YTD-to-quarterly conversion (free)

## Usage

```bash
# Run full S&P 500, output both files (default)
python fetch_sp_growth.py

# Only output sp100growth.json (processes S&P 100 only)
python fetch_sp_growth.py --sp100-only

# Only output sp500growth.json (processes S&P 500)
python fetch_sp_growth.py --sp500-only

# Output to a different directory
python fetch_sp_growth.py --output ./my_output

# Use a different config file
python fetch_sp_growth.py --config ./custom_config.yml
```

## Output Files

| File | Description | Companies |
|------|-------------|-----------|
| `output/sp100growth.json` | S&P 100 growth metrics | ~100 mega-cap |
| `output/sp500growth.json` | S&P 500 growth metrics | ~500 large-cap |

## Output Format

Both output files use the same format:

```json
{
  "_README": {
    "title": "S&P 500 Growth Metrics",
    "description": "Financial growth metrics extracted from SEC EDGAR filings",
    "metrics_explained": { ... }
  },
  "metadata": {
    "generated_at": "2025-12-08T04:15:00Z",
    "data_sources": "SEC EDGAR + yfinance + Alpha Vantage + Finnhub",
    "ticker_count": 500,
    "successful_extractions": 490,
    "universe": "S&P 500"
  },
  "companies": {
    "AAPL": {
      "ticker": "AAPL",
      "sector": "Information Technology",
      "cik": "0000320193",
      "company_name": "Apple Inc.",
      "extracted_at": "2025-12-08T04:15:00Z",
      "annual_values": {
        "2024": {"revenue": 391035000000, "eps": 6.08},
        "2023": {"revenue": 383285000000, "eps": 6.13},
        "2022": {"revenue": 394328000000, "eps": 6.11}
      },
      "quarterly_values": {
        "2024-Q3": {"revenue": 94930000000, "eps": 1.40},
        "2024-Q2": {"revenue": 85777000000, "eps": 1.53},
        "2024-Q1": {"revenue": 90753000000, "eps": 1.53}
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
        "eps_cagr_3yr": 0.019
      }
    }
  }
}
```

## Metrics Explained

### Annual Values
- `annual_values[year].revenue`: Annual revenue in USD
- `annual_values[year].eps`: Annual diluted EPS in USD per share

### Quarterly Values
- `quarterly_values[quarter].revenue`: Quarterly revenue in USD
- `quarterly_values[quarter].eps`: Quarterly diluted EPS in USD per share

### Growth Rates
- `revenue_yoy`: Year-over-year revenue growth (decimal, 0.05 = 5%)
- `eps_yoy`: Year-over-year EPS growth (decimal)
- `ttm.revenue_yoy`: TTM revenue growth vs prior 12 months
- `ttm.eps_yoy`: TTM EPS growth vs prior 12 months
- `revenue_cagr_3yr`: 3-year compound annual growth rate
- `eps_cagr_3yr`: 3-year EPS CAGR
- `revenue_cagr_5yr`: 5-year revenue CAGR
- `eps_cagr_5yr`: 5-year EPS CAGR

## Configuration

Edit `config.yml` to customize:

```yaml
user_agent: "YourEmail@example.com"
years_to_fetch: 7
quarters_to_fetch: 12
yfinance_enabled: true
finnhub_enabled: true
alphavantage_enabled: true
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FINNHUB_API_KEY` | Recommended | For quarterly data fallback |
| `ALPHA_VANTAGE_API_KEY` | Optional | For annual data fallback |

## Migration from SP100 Growth

This collector replaces the original `sp100growth/fetch_sp100_growth.py`. The original collector is still available for reference but the workflow has been updated to use this unified version.

Key differences:
- Processes full S&P 500 instead of just S&P 100
- Outputs two files from a single run
- More efficient (no duplicate API calls)
- Workflow renamed from `sp100-growth.yml` to `sp-growth.yml`

## Notes

- All growth rates are decimals (multiply by 100 for percentage)
- Null values indicate insufficient data from all sources
- Revenue figures are in USD (not scaled)
- Fiscal year end dates vary by company
- Processing ~500 companies takes approximately 15-20 minutes
