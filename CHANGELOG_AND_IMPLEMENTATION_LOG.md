# DeanFi Collectors - Changelog and Implementation Log

## Overview
This document tracks all implementations, changes, and updates to the DeanFi Collectors project. It serves as a comprehensive history of the codebase evolution.

# DeanFi Collectors - Changelog and Implementation Log

## 2025-11-28: Extended Holiday Gap Fix to All Major Index Collectors

### Summary
Extended the `get_current_snapshot_from_info()` fix to all major index collectors. The same holiday gap issue that affected commodity futures also affects US indices, treasury yields, international indices, and any other instrument that may have gaps in historical data around market holidays.

### Root Cause (Same as Commodity Fix)
- Yahoo Finance historical data can have gaps around holidays (Thanksgiving, Christmas, etc.)
- US indices (^GSPC, ^DJI, etc.) were missing Nov 27 data, jumping from Nov 26 to Nov 28
- Treasury yields, international indices, and currency indices have similar gap patterns
- Using `df.iloc[-2]` as "previous close" resulted in multi-day returns instead of 1-day returns

### Solution
Updated all major index collectors to use `get_current_snapshot_from_info()` which fetches `ticker.info` from yfinance for accurate daily change data. This uses Yahoo's correctly calculated `regularMarketChangePercent` value.

### Collectors Updated
| Collector | Symbols | Risk Level |
|-----------|---------|------------|
| fetch_bonds.py | ^TNX, ^TYX, ^FVX, ^IRX | HIGH - US market holidays |
| fetch_currency.py | DX-Y.NYB | HIGH - Market holidays |
| fetch_us_major.py | ^GSPC, ^DJI, ^IXIC, ^NDX, ^RUT, ^VIX | HIGH - Confirmed gap |
| fetch_dow_family.py | ^DJI, ^DJT, ^DJU, ^DJA | HIGH - US holidays |
| fetch_growth_value.py | ^RLG, ^RLV, ^RUO, ^RUJ, ^RUA | HIGH - Russell indices |
| fetch_international.py | ^FTSE, ^N225, ^HSI, etc. | MEDIUM - Different holidays |
| fetch_emerging.py | ^BVSP, ^MXX, ^BSESN, etc. | MEDIUM - Different holidays |
| fetch_equal_weight.py | ^SPXEW, ^NDXE, RSP, QQEW | MEDIUM - Indices + ETFs |
| fetch_sectors.py | XLK, XLV, XLF, etc. | LOW - ETFs, but benchmark fixed |
| fetch_commodities.py | GC=F, SI=F, CL=F, NG=F | HIGH - Already fixed |

### Code Pattern Applied
Each collector was updated with this pattern:
```python
# Old approach (vulnerable to holiday gaps)
snapshot = get_current_snapshot(df)

# New approach (uses Yahoo's calculated daily change)
ticker = yf.Ticker(symbol)
ticker_info = ticker.info
snapshot = get_current_snapshot_from_info(ticker_info, df)
```

### Import Changes
Updated imports from `from utils import *` to explicit imports including `get_current_snapshot_from_info` for better code clarity.

### Testing
All 10 collectors run successfully and generate valid JSON with correct daily change percentages matching Yahoo Finance's reported values.

---

## 2025-11-28: Fixed Commodity Futures Daily Change Calculation

### Summary
Fixed a bug where commodity futures (Gold, Silver, Oil, Natural Gas) were showing incorrect daily change percentages - often nearly double the actual change. The issue occurred because yfinance historical data for futures has gaps around holidays (like Thanksgiving), causing the "previous day" to actually be several days ago.

### Root Cause
- Yahoo Finance's historical data for commodity futures (`GC=F`, `SI=F`, etc.) has gaps around market holidays
- For example, around Thanksgiving 2025, Gold data jumped from Nov 24 directly to Nov 28, missing Nov 25-27
- The original code calculated daily change as `(current - df.iloc[-2]) / df.iloc[-2]`
- This meant we were calculating 4-day returns instead of 1-day returns

### Solution
Created a new `get_current_snapshot_from_info()` function in `utils.py` that uses `ticker.info` from yfinance instead of historical data. Yahoo's `ticker.info` provides:
- `regularMarketPrice` - Current price
- `regularMarketPreviousClose` - Actual previous close (correct value)
- `regularMarketChange` - Daily change in dollars
- `regularMarketChangePercent` - Daily change percentage

These values are correctly calculated by Yahoo Finance regardless of gaps in historical data.

### Changes Made
- **majorindexes/utils.py**: Added `get_current_snapshot_from_info()` function that extracts snapshot data from `ticker.info` with fallback to DataFrame for OHLV data
- **majorindexes/fetch_commodities.py**: Updated `create_snapshot_json()` to:
  - Fetch `ticker.info` for each commodity
  - Use `get_current_snapshot_from_info()` instead of `get_current_snapshot()` for daily change calculations
  - Continue using historical DataFrame for 52-week metrics, returns, and pivot points

### Before/After Comparison (Nov 28, 2025)
| Commodity | Before (Wrong) | After (Correct) |
|-----------|----------------|-----------------|
| Gold (GC=F) | 3.42% | 1.02% |
| Silver (SI=F) | 11.18% | 6.10% |
| Oil (CL=F) | 0.44% | 1.43% |

### Notes
- This fix specifically addresses commodity futures which trade on different schedules than stock markets
- The original `get_current_snapshot()` function is preserved for backwards compatibility with equity indices that don't have holiday gaps
- The new function also provides more accurate intraday data (high, low, open, volume) from the real-time quote

---

## 2025-11-28: Market Data 10-Minute Cadence + Doc Refresh

### Summary
Modernized the high-frequency workflow and documentation to reflect the new 10-minute market data cadence, consolidating breadth, index, implied volatility, and mean reversion collectors under the renamed `market-data-10min.yml`. All developer-facing docs, checklists, and dataset metadata now describe the updated schedule and runtime expectations. Cron expressions follow [GitHub's official schedule syntax guidance](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) to ensure the 5-minute step interval stays compliant.

### Changes Made
- **.github/workflows/market-data-10min.yml** – Documented the 10-minute cron windows (13-21 UTC EST / 12-20 UTC EDT) and clarified the 5-minute offset rationale.
- **README.md** – Updated badges, data collector table, runtime estimates, and schedule section to describe the new cadence and consolidated workflow.
- **.github/workflows/README.md** – Replaced the outdated workflow inventory with the current five workflows, refreshed schedule breakdowns, and simplified secret usage notes.
- **INITIAL_COMMIT_CHECKLIST.md** – Adjusted the setup tasks to reference `market-data-10min.yml`, the nightly workflows, and the modern repo description ("Runs every 10min").
- **meanreversion/config.yml**, **meanreversion/fetch_price_vs_ma.py**, **meanreversion/fetch_ma_spreads.py** – Updated `_README` metadata strings so downstream consumers see the correct "Every 10 minutes during market hours" frequency.

### Notes
- GitHub Actions cron scheduling cannot run more frequently than every 5 minutes; the `5-55/10` syntax keeps executions evenly spaced while staggering starts away from the top of the hour per GitHub's scheduling best practices.
- Documentation should reference the `market-data-10min` workflow whenever discussing market breadth, major index, implied volatility, or mean reversion collectors to avoid confusion with the retired per-collector workflows.

---

## 2025-11-27: Nightly Earnings & Analyst Trend Schedules

### Summary
Updated the GitHub Actions schedules for the earnings calendar/surprises and analyst recommendation collectors to run every weekday night at 11:00pm Eastern (04:00 UTC). Running nightly keeps the datasets fresh ahead of each trading day without colliding with other collectors writing to `deanfi-data`.

### Changes Made
- **.github/workflows/earnings.yml** – Replaced the weekly Sunday cron with `0 4 * * 2-6` (Tue–Sat at 04:00 UTC) and clarified the inline comment that this maps to 11:00pm EST / midnight EDT.
- **.github/workflows/analyst-trends.yml** – Applied the same cron expression and explanatory comment so recommendation trends refresh on the same cadence.

### Notes
- GitHub Actions uses UTC for cron expressions. Scheduling at 04:00 UTC ensures a consistent 11:00pm Eastern run, shifting to midnight during daylight saving time while still capturing end-of-day data.
- No code or dependency changes were required; only workflow configuration updates were made.

---

## 2024-11-24: Switched from Market Indices to ETFs

### Summary
Updated mean reversion collector to use ETFs (SPY, QQQ, IWM) instead of market indices (^GSPC, ^IXIC, ^RUT) for better data reliability, fewer gaps, and actual tradeability for backtesting purposes. Also resolved null z-score issues by implementing proper warmup period.

### Changes Made

#### Configuration Updates
- **config.yml**: 
  - Replaced ^GSPC with SPY (SPDR S&P 500 ETF Trust) tracking S&P 500
  - Replaced ^IXIC with QQQ (Invesco QQQ Trust) tracking Nasdaq-100
  - Replaced ^RUT with IWM (iShares Russell 2000 ETF) tracking Russell 2000
  - Added `tracks_index` field to show which index each ETF tracks
  - Added `warmup_days: 452` to ensure clean z-score data
  - Updated `fetch_days: 956` to include warmup period
  - Changed output_dir to "output" for local testing
  - Changed fetch period from "2y" to "5y" to ensure sufficient data

#### Code Updates
- **fetch_price_vs_ma.py**:
  - Added `tracks_index` parameter to `calculate_price_vs_ma_for_index()`
  - Updated function to include ETF tracking information in output
  - Updated docstrings from "index" to "ETF" terminology
  - Implemented WARMUP_DAYS-based trimming to skip first 452 days
  - Ensures 504 days of output with zero null z-scores
  
- **fetch_ma_spreads.py**:
  - Added `tracks_index` parameter to `calculate_ma_spreads_for_index()`
  - Updated function to include ETF tracking information in output
  - Updated docstrings from "index" to "ETF" terminology
  - Implemented WARMUP_DAYS-based trimming to skip first 452 days
  - Ensures 504 days of output with zero null z-scores

#### Output Changes
- JSON files now include `tracks_index` field for each ETF showing what they track:
  - SPY tracks "S&P 500"
  - QQQ tracks "Nasdaq-100"
  - IWM tracks "Russell 2000"
- Output directory changed to `meanreversion/output/` for local testing
- Added `meanreversion/output/` to .gitignore to prevent test data commits
- **Data Quality**: All 504 historical records now have complete z-score data with zero nulls

#### Documentation Updates
- Updated README.md in deanfi-data to reflect ETF usage
- Updated DEVELOPER_REQUIREMENTS.md with warmup period details
- Updated all comments and docstrings to use ETF terminology

### Technical Details

**Warmup Period Calculation**:
```
- 200 days: Required for 200-day MA to stabilize
- 252 days: Required for z-score lookback calculation
- Total warmup: 452 days
- Output period: 504 days (2 years)
- Total fetch: 956 days (~3.8 years from 5y period)
```

**Data Quality Achievement**:
- Fetches 956 days of price data (5y period provides ~1256 days)
- Skips first 452 days (warmup period)
- Outputs days 453-956 (504 days total)
- Result: **Zero null values** in all z-score calculations

### Rationale
While yfinance does provide historical data for market indices, ETFs offer several advantages:
1. More reliable data with fewer gaps
2. Actually tradeable instruments (useful for backtesting)
3. Better data consistency across providers
4. Standard trading hours and no special handling needed
5. Institutional traders use ETFs for these exact calculations

---

## 2024-11-24: Mean Reversion Indicators Collector

### Summary
Added comprehensive mean reversion analysis collector tracking price deviations from moving averages and MA spread patterns for major US market ETFs. This provides institutional-grade statistical signals for identifying overbought/oversold conditions.

### New Files Created

#### `/meanreversion/` Directory
- **config.yml**: Configuration for mean reversion calculations
  - Defines 3 ETFs to track: SPY (S&P 500), QQQ (Nasdaq-100), IWM (Russell 2000)
  - MA periods: 20, 50, 200 days
  - Historical lookback: 504 days (2 years output)
  - Fetch period: 956 days (includes 452-day warmup)
  - Z-score lookback: 252 days (1 year)
  - Warmup days: 452 (200 for MA + 252 for z-score)
  - Comprehensive metric descriptions and trading applications
  
- **utils.py**: Mean reversion calculation utilities
  - `calculate_sma()`: Simple moving average calculation
  - `calculate_all_mas()`: Calculate multiple MAs at once
  - `calculate_price_distance()`: Point distance between price and MA
  - `calculate_price_distance_percent()`: Percentage distance from MA
  - `calculate_price_zscore()`: Statistical z-score of price vs MA
  - `calculate_all_price_vs_ma_metrics()`: Comprehensive price vs MA analysis
  - `calculate_ma_spread()`: Point spread between two MAs
  - `calculate_ma_spread_percent()`: Percentage spread between MAs
  - `calculate_ma_spread_zscore()`: Statistical z-score of MA spread
  - `calculate_all_ma_spread_metrics()`: Comprehensive MA spread analysis
  - Helper functions: `determine_signal()`, `determine_trend_alignment()`, `safe_float()`
  - Data formatting: `format_timestamp()`, `format_date()`, `save_json()`, `create_metadata()`
  - Validation: `validate_sufficient_data()`, `get_data_quality_status()`

- **fetch_price_vs_ma.py**: Price vs moving average collector
  - Fetches 956 days of price data for 3 ETFs (5y period)
  - Calculates distance, percent, and z-score for 20/50/200-day MAs
  - Implements 452-day warmup period for clean z-score data
  - Outputs 504 days with zero null values
  - Generates comprehensive snapshot and historical JSONs
  - Uses CachedDataFetcher for performance optimization
  - Includes detailed _README section with formulas and interpretations
  
- **fetch_ma_spreads.py**: Moving average spread collector
  - Fetches 956 days of price data for 3 ETFs (5y period)
  - Calculates spreads for 3 MA pairs: 20-50, 20-200, 50-200
  - Implements 452-day warmup period for clean z-score data
  - Outputs 504 days with zero null values
  - Computes spread, percent spread, and z-score for each pair
  - Identifies golden cross / death cross signals
  - Generates comprehensive snapshot and historical JSONs
  - Uses CachedDataFetcher for performance optimization

#### Workflow
- **.github/workflows/mean-reversion.yml**: Automated collection workflow
  - Runs every 15 minutes during market hours (9:30am-4:15pm ET)
  - Executes both price vs MA and MA spreads collectors
  - Uses caching for optimal performance
  - Commits results to deanfi-data repository
  - Prevents concurrent runs to avoid conflicts

#### Data Repository
- **/deanfi-data/meanreversion/README.md**: Comprehensive dataset documentation
  - Explains mean reversion theory and applications
  - Documents all metrics with formulas and interpretations
  - Provides trading strategy examples
  - Includes professional tips and best practices
  - UI/UX guidelines for data visualization
  - Color coding standards (20-day=green, 50-day=blue, 200-day=purple)

### Updated Files

#### `/README.md`
- Added "Mean Reversion" to Data Collectors table
- Added meanreversion directory to project structure
- Added fetch commands to "Running Collectors Locally" section

#### `/.github/workflows/README.md`
- Added mean-reversion.yml to workflows overview table
- Updated total categories from 11 to 12
- Updated monthly runtime hours from ~89h to ~109h

### Technical Implementation Details

#### Calculations
1. **Price vs MA Metrics**:
   - Distance: `current_price - ma_value`
   - Distance %: `(current_price - ma_value) / ma_value * 100`
   - Z-Score: `(current_price - ma) / std_dev(price - ma)` over 252-day window

2. **MA Spread Metrics**:
   - Spread: `ma_short - ma_long`
   - Spread %: `(ma_short - ma_long) / ma_long * 100`
   - Z-Score: `(current_spread - mean_spread) / std_dev(spread)` over 252-day window

3. **Signal Interpretation**:
   - Z-score > 2: Extremely overbought (>95th percentile)
   - Z-score < -2: Extremely oversold (<5th percentile)
   - Z-score -1 to 1: Normal range

#### Data Structure
Both collectors generate two JSON files:

**Snapshot Files**:
- Current values only
- Include all metrics and signals
- Trend alignment indicators
- Golden/death cross status

**Historical Files**:
- 504 days of data (2 years)
- Daily records with all metrics
- Enables backtesting and pattern analysis
- Data quality metrics

#### Indices Tracked
- **^GSPC**: S&P 500 (Large-cap benchmark)
- **^IXIC**: Nasdaq Composite (Tech-heavy)
- **^RUT**: Russell 2000 (Small-cap benchmark)

#### Moving Averages
- **20-day**: Short-term trend (~1 month)
- **50-day**: Intermediate trend (~2.5 months)
- **200-day**: Long-term trend (~1 year)

#### MA Pairs
- **20 vs 50**: Swing trading timeframe
- **20 vs 200**: Trend validation
- **50 vs 200**: Major trend changes (Golden/Death Cross)

### Output Files (in deanfi-data/meanreversion/)
- `price_vs_ma_snapshot.json`: Current price vs MA metrics
- `price_vs_ma_historical.json`: 504-day historical price vs MA data
- `ma_spreads_snapshot.json`: Current MA spread metrics
- `ma_spreads_historical.json`: 504-day historical MA spread data

### Trading Applications
1. **Mean Reversion Strategy**: Use extreme z-scores (>2 or <-2) as contrarian signals
2. **Trend Following Filter**: Combine with 200-day MA for directional bias
3. **Overbought/Oversold**: Identify stretched conditions using percent distance >5%
4. **MA Crossover Confirmation**: Monitor spread changes for trend reversals
5. **Golden/Death Cross**: Track 50-day vs 200-day crossovers

### Dependencies
All dependencies already in requirements.txt:
- yfinance: Data fetching
- pandas: Data manipulation
- numpy: Statistical calculations
- PyYAML: Config loading

### Testing Performed
- ✅ Python syntax validation (py_compile)
- ✅ YAML configuration validation
- ✅ Workflow YAML validation
- ✅ Config settings verification (3 indices, [20,50,200] MAs, 504 days)

### Integration Points
- Uses shared/cache_manager.py for intelligent caching
- Follows existing collector patterns
- Integrates with GitHub Actions workflows
- Auto-syncs to Cloudflare R2 via existing workflow
- Compatible with deanfi-website UI standards

### Performance Optimization
- CachedDataFetcher reduces API calls by 80-90%
- Parquet caching enables incremental updates
- Single workflow executes both collectors
- Expected runtime: ~2 minutes per execution

### Documentation Standards
All outputs include:
- Comprehensive _README sections
- Formula documentation
- Interpretation guidelines
- Trading applications
- Professional usage tips
- Data quality metrics
- Metadata tracking

---

## Initial Implementation (Pre-2024-11-24)

### Existing Structure
The DeanFi Collectors project was established with the following collectors:

#### Market Data Collectors (15-minute intervals)
1. **advancedecline/**: Market breadth indicators
   - Advances/declines ratio
   - Volume metrics
   - 52-week highs/lows
   - Stocks above 20/50/200-day MAs

2. **majorindexes/**: Index tracking
   - US major indices (S&P 500, Dow, Nasdaq, Russell 2000)
   - Sector indices
   - International indices
   - Bond and commodity indices
   - Technical indicators (SMA, RSI, MACD, Bollinger Bands)

3. **impliedvol/**: Volatility metrics
   - VIX tracking
   - Sector ETF implied volatility
   - Options data

#### News & Analyst Data (Scheduled)
4. **dailynews/**: Market news
   - Top market news (twice daily)
   - Sector news breakdowns
   - Finnhub integration

5. **analysttrends/**: Analyst recommendations
   - Buy/hold/sell rating changes
   - Sector aggregations
   - Leading company analysis

6. **earningscalendar/**: Earnings dates
   - Upcoming earnings releases
   - Estimate tracking

7. **earningssurprises/**: Historical earnings
   - EPS vs estimates
   - Surprise analysis
   - Sector aggregations

#### Economic Indicators (Daily)
8. **growthoutput/**: Growth metrics
   - GDP
   - Industrial production
   - Capacity utilization

9. **inflationprices/**: Inflation tracking
   - CPI
   - PCE
   - PPI
   - Breakeven inflation

10. **laboremployment/**: Labor market
    - Unemployment rates
    - Payrolls
    - Wages
    - Job openings

11. **moneymarkets/**: Interest rates
    - Fed funds rate
    - Treasury yields
    - Yield curve
    - M2 money supply

### Shared Utilities
- **cache_manager.py**: Intelligent caching system
  - Incremental downloads
  - Parquet storage
  - Self-healing
  - Metadata tracking

- **spx_universe.py**: S&P 500 constituent management
  - Wikipedia scraping
  - Fallback list
  - Ticker validation

- **fred_client.py**: FRED API wrapper
  - Error handling
  - Rate limiting
  - Data validation

- **economy_*.py**: Economic data utilities
  - Indicator definitions
  - Computation logic
  - Grading algorithms
  - I/O operations

- **sector_mapping.py**: Sector classification
  - GICS sector mapping
  - Consistent categorization

### Infrastructure
- GitHub Actions workflows for automation
- deanfi-data repository for storage
- Cloudflare R2 for CDN distribution
- Parquet caching for performance

---

## Future Enhancements

### Planned Features
- [ ] Relative strength analysis (RS vs benchmarks)
- [ ] Momentum indicators (rate of change, RSI extremes)
- [ ] Volume profile analysis
- [ ] Options flow tracking
- [ ] Sentiment indicators
- [ ] Insider trading tracking

### Performance Improvements
- [ ] Parallel data fetching
- [ ] Redis caching layer
- [ ] Delta compression for historical data
- [ ] GraphQL API for data consumption

### Documentation
- [ ] Video tutorials for using collectors
- [ ] API documentation generation
- [ ] Trading strategy examples
- [ ] Backtest result sharing

---

## Notes for AI Assistants

### When Working on This Project
1. Always check this CHANGELOG before making changes
2. Update this log with any new implementations
3. Reference the DEVELOPER_REQUIREMENTS.md for coding standards
4. Test locally before committing
5. Update relevant README files
6. Validate YAML configurations
7. Follow existing patterns and conventions

### Code Conventions
- Use CachedDataFetcher for yfinance data
- Include comprehensive _README in all JSON outputs
- Document formulas and interpretations
- Follow color coding standards for UI integration
- Handle errors gracefully
- Log warnings for data quality issues
- Validate configurations at startup

### Testing Checklist
- [ ] Syntax validation (`python -m py_compile`)
- [ ] YAML validation
- [ ] Local test run with cache
- [ ] Verify JSON output structure
- [ ] Check workflow execution
- [ ] Confirm data in deanfi-data repo
- [ ] Verify R2 sync

---

*This log is maintained to ensure continuity and understanding of the project's evolution. Keep it updated with every significant change.*
