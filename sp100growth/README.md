# SP100 Growth Collector

Extracts annual (10-K) and quarterly (10-Q) financial data from SEC EDGAR for S&P 100 companies, with Finnhub fallback for quarterly data.

## What It Does

1. Fetches S&P 100 ticker list from Wikipedia (with CSV fallback)
2. Retrieves annual (10-K) and quarterly (10-Q) filings from SEC EDGAR
3. Extracts **Revenue** and **EPS (Diluted)** metrics
4. Calculates **Year-over-Year growth rates**, **TTM metrics**, and **CAGR**
5. Falls back to Finnhub for missing quarterly data
6. Outputs a single **sp100growth.json** file

## Data Sources

- **Primary**: SEC EDGAR (10-K and 10-Q filings)
- **Fallback**: Finnhub API (for quarterly data when SEC is incomplete)
- **Universe**: Wikipedia S&P 100 constituents (with CSV fallback)

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
      "cik": "0000320193",
      "company_name": "Apple Inc.",
      "extracted_at": "2025-12-06T23:30:00Z",
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

## Files

| File | Description |
|------|-------------|
| `fetch_sp100_growth.py` | Main extraction script |
| `config.yml` | Configuration file |

The S&P 100 universe is fetched from `shared/sp100_universe.py`.

## Dependencies

- `secedgar` - SEC EDGAR API client
- `pandas` - Data handling
- `pyyaml` - Config parsing
- `requests` - HTTP requests

These are included in the project's `requirements.txt`.

## Schedule

Runs nightly at 11:15pm Eastern (04:15 UTC) via GitHub Actions, 15 minutes after the analyst-trends and earnings collectors.

## Special Ticker Handling

- **BRK.B** → **BRK-B**: Wikipedia uses BRK.B but SEC EDGAR uses BRK-B
- **GOOGL vs GOOG**: Deduplicates to GOOGL (Class A shares)
