# DeanFi Collectors - Developer Requirements

## Overview
DeanFi Collectors is a Python-based data collection pipeline that fetches financial market data from various sources (Finnhub, FRED, Yahoo Finance) and publishes to the deanfi-data repository. Data is updated automatically via GitHub Actions workflows running during market hours and on scheduled intervals.

## Project Goals
- **Reliability**: Ensure data collection runs consistently without failures
- **Performance**: Minimize API calls and runtime through intelligent caching
- **Maintainability**: Clear code structure with shared utilities
- **Scalability**: Easy to add new data collectors
- **Data Quality**: Validate and enrich data with metadata and interpretations

## Technology Stack

### Core Technologies
- **Python 3.8+**: Primary language for all collectors
- **yfinance**: Yahoo Finance data extraction
- **pandas**: Data manipulation and time series analysis
- **numpy**: Numerical calculations and statistics
- **PyYAML**: Configuration file management
- **requests**: HTTP requests for API calls

### Data Sources
- **Yahoo Finance (yfinance)**: Market indices, breadth, volatility, mean reversion metrics
  - No API key required
  - Rate limits: ~2000 requests/hour
  - Documentation: https://github.com/ranaroussi/yfinance
  
- **Finnhub API**: News, analyst trends, earnings data
  - Free tier: 60 calls/minute
  - Requires API key: https://finnhub.io/register
  - Documentation: https://finnhub.io/docs/api
  
- **FRED API**: Economic indicators (GDP, CPI, unemployment, etc.)
  - Free tier: 120 calls/minute
  - Requires API key: https://fred.stlouisfed.org/docs/api/api_key.html
  - Documentation: https://fred.stlouisfed.org/docs/api/fred/

### Infrastructure
- **GitHub Actions**: Automated workflow execution
- **Parquet**: Efficient data caching format
- **JSON**: Output data format for deanfi-data repository

## Architecture

### Directory Structure
```
deanfi-collectors/
├── .github/workflows/       # Automated collection workflows
├── shared/                  # Shared utilities across all collectors
│   ├── cache_manager.py    # Intelligent caching system
│   ├── spx_universe.py     # S&P 500 ticker management
│   ├── fred_client.py      # FRED API wrapper
│   ├── economy_*.py        # Economic data utilities
│   └── sector_mapping.py   # Sector classification
├── [collector_name]/        # Individual collector directories
│   ├── fetch_*.py          # Data collection scripts
│   ├── utils.py            # Collector-specific utilities
│   ├── config.yml          # Configuration
│   └── *.json              # Output files (gitignored)
└── requirements.txt         # Python dependencies
```

### Shared Modules

#### CachedDataFetcher (cache_manager.py)
- **Purpose**: Minimize API calls and improve performance
- **Strategy**: 
  - Cache < 24 hours: Incremental update (last 5 days)
  - Cache 24-168 hours: Download last 10 days
  - Cache > 168 hours: Full rebuild
- **Storage**: Parquet format with metadata tracking
- **Usage**: All yfinance-based collectors

#### S&P 500 Universe (spx_universe.py)
- **Purpose**: Maintain consistent list of S&P 500 constituents
- **Source**: Wikipedia S&P 500 table
- **Fallback**: Hardcoded list if Wikipedia unavailable
- **Usage**: Market breadth, analyst trends, earnings

#### FRED Client (fred_client.py)
- **Purpose**: Wrapper for FRED API calls
- **Features**: Error handling, rate limiting, data validation
- **Usage**: All economy-related collectors

### Data Collection Patterns

#### 1. Real-time Market Data (10-minute intervals)
**Collectors**: advancedecline, majorindexes, impliedvol, meanreversion

**Pattern**: 
```python
# Use caching to minimize downloads
fetcher = CachedDataFetcher(cache_dir="cache")
df = fetcher.fetch_prices(tickers, period="1y", cache_name="collector_name")

# Calculate metrics
metrics = calculate_metrics(df)

# Save output JSON
save_json(output_data, "output_file.json")
```

**Requirements**:
- Must use CachedDataFetcher for yfinance calls
- Include comprehensive metadata and interpretations
- Handle market hours vs after-hours appropriately
- Validate data quality before saving
#### Market Data Collectors (10-minute intervals)

#### 2. Scheduled News/Analyst Data
**Collectors**: dailynews, analysttrends, earningscalendar, earningssurprises

**Pattern**:
```python
# Initialize API client
client = FinnhubClient(api_key)

# Fetch data
data = client.fetch_endpoint(params)

# Process and enrich
enriched_data = process_and_aggregate(data)

**Pattern**: 
save_json(enriched_data, "output_file.json")
```

**Requirements**:
- Respect API rate limits
- Handle API errors gracefully
- Aggregate/analyze raw data for insights
- Include sector breakdowns where applicable

#### 3. Economic Indicators (Daily)
**Collectors**: growthoutput, inflationprices, laboremployment, moneymarkets

**Pattern**:
```python
# Load indicator definitions from config
indicators = load_config()['indicators']

# Fetch from FRED
fred = FREDClient(api_key)
data = fred.fetch_multiple_series(indicators)

# Compute derived metrics
computed = compute_economic_breadth(data)

# Save structured output
save_json(computed, "output_file.json")
```

**Requirements**:
- Use economy_* shared modules for consistency
- Include economic grading/interpretation
- Handle missing/delayed data appropriately
- Provide historical context

## Coding Standards

### Python Style
- **PEP 8**: Follow standard Python style guide
- **Type hints**: Use for function signatures where helpful
- **Docstrings**: Required for all public functions
- **Error handling**: Catch and log specific exceptions
- **Comments**: Explain complex calculations and formulas

### Configuration Files (config.yml)
- **Structure**: YAML format with clear sections
- **Documentation**: Include descriptions and interpretations
- **Validation**: Ensure configs are loaded and validated at runtime
- **Defaults**: Provide sensible defaults for all optional settings

### Output JSON Structure
All JSON outputs must include:

```json
{
  "_README": {
    "title": "Dataset name",
    "description": "What this data represents",
    "purpose": "Why this data is useful",
    "metrics_explained": {
      "metric_name": {
        "description": "What it measures",
        "formula": "How it's calculated",
        "interpretation": "How to use it"
      }
    },
    "trading_applications": {
      "use_case": "Practical trading application"
    }
  },
  "metadata": {
    "generated_at": "ISO 8601 timestamp",
    "data_source": "Source name",
    "indices_count": 0
  },
  "data": {
    // Actual data
  }
}
```

**Requirements**:
- Educational: Anyone should understand the data
- Formulas: Include calculation formulas
- Interpretations: Explain what values mean
- Applications: Show practical use cases
- Metadata: Track generation time and source

## Color Coding Standards (UI Integration)

When data will be displayed in UI:
- **20-Day MA**: Green (#10b981)
- **50-Day MA**: Blue (primary)
- **200-Day MA**: Purple (#9333ea)
- **Performance badges**: 
  - Green (>5%)
  - Blue (0-5%)
  - Orange (0 to -5%)
  - Red (<-5%)

## Testing Requirements

### Local Testing
Before committing:
```bash
# Syntax check
python -m py_compile script.py

# YAML validation
python -c "import yaml; yaml.safe_load(open('config.yml'))"

# Test run (with cache)
python fetch_script.py --cache-dir ./test_cache

# Verify output
cat output.json | jq '.metadata'
```

### Workflow Testing
- Use `workflow_dispatch` for manual testing
- Check GitHub Actions logs for errors
- Verify data appears in deanfi-data repo
- Confirm R2 sync completes successfully

## Performance Optimization

### Caching Strategy
- **Use CachedDataFetcher** for all yfinance calls
- Cache files stored in deanfi-data/cache/ directory
- Parquet format is 10x faster than CSV
- Incremental updates minimize API calls

### API Rate Limits
- **Finnhub Free**: 60 calls/minute
- **FRED Free**: 120 calls/minute
- **yfinance**: ~2000 requests/hour
- Use batching where possible
- Implement backoff/retry logic

### Runtime Targets
- Market data collectors: < 3 minutes
- News/analyst collectors: < 5 minutes
- Economic collectors: < 3 minutes

## Security Best Practices

### API Keys
- Never commit API keys to repository
- Use GitHub Secrets for all credentials
- Use .env for local development
- Provide .env.example template

### Data Validation
- Validate input data before processing
- Handle missing/null values appropriately
- Check data ranges for anomalies
- Log warnings for unexpected values

## Deployment

### GitHub Actions Setup
1. Fork/clone repository
2. Add secrets to GitHub repository settings:
   - `FINNHUB_API_KEY`
   - `FRED_API_KEY`
   - `DATA_REPO_TOKEN` (Personal Access Token with repo scope)
3. Enable GitHub Actions
4. Test with manual workflow_dispatch trigger

### Environment Variables
Required in .env (local) or GitHub Secrets (production):
- `FINNHUB_API_KEY`: Finnhub API key
- `FRED_API_KEY`: FRED API key
- `DATA_REPO_TOKEN`: GitHub PAT for pushing to deanfi-data

## Adding New Collectors

### Step-by-Step Process

1. **Create Directory**
   ```bash
   mkdir [collector_name]
   cd [collector_name]
   ```

2. **Create config.yml**
   - Define data sources
   - Document metrics
   - Include interpretations

3. **Create fetch_*.py**
   - Import shared utilities
   - Fetch data with caching
   - Calculate metrics
   - Save enriched JSON

4. **Create utils.py** (if needed)
   - Collector-specific calculations
   - Data formatting functions
   - Helper utilities

5. **Create workflow**
   - Copy existing workflow template
   - Adjust schedule and steps
   - Add to workflows README

6. **Update Documentation**
   - Add to main README collectors table
   - Update project structure
   - Document in CHANGELOG

7. **Test Locally**
   ```bash
   python fetch_script.py --cache-dir ./test_cache
   ```

8. **Test Workflow**
   - Trigger workflow_dispatch
   - Check logs and output
   - Verify data in deanfi-data

## Documentation Requirements

### Code Documentation
- Docstrings for all public functions
- Inline comments for complex logic
- Formula documentation for calculations
- Example usage in docstrings

### README Files
- Main README: Overview and quick start
- Collector READMEs: Dataset-specific details
- Workflow README: Automation documentation

### JSON Documentation
- _README section in every JSON
- Metric explanations
- Trading applications
- Interpretation guidelines

## Dependencies Management

### requirements.txt
Keep dependencies minimal and pinned:
```
yfinance>=0.2.28
pandas>=2.0.0
numpy>=1.24.0
PyYAML>=6.0
requests>=2.31.0
```

### Version Updates
- Test before updating major versions
- Document breaking changes
- Update requirements.txt
- Test all collectors after updates

## References

### Official Documentation
- yfinance: https://github.com/ranaroussi/yfinance
- Finnhub: https://finnhub.io/docs/api
- FRED: https://fred.stlouisfed.org/docs/api/fred/
- pandas: https://pandas.pydata.org/docs/
- GitHub Actions: https://docs.github.com/en/actions

### Best Practices
- PEP 8: https://pep8.org/
- Python Docstrings: https://peps.python.org/pep-0257/
- YAML Spec: https://yaml.org/spec/
- JSON Schema: https://json-schema.org/

## Support and Contributing

See CONTRIBUTING.md for:
- Code contribution guidelines
- Pull request process
- Issue reporting
- Feature requests
