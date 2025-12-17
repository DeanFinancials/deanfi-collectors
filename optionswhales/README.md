# Options Whale Collector

Detects large OTM (Out of the Money) options trades ("whale trades") for S&P 500 constituents using the Alpaca Markets Options API.

## Overview

This collector scans the entire S&P 500 for significant options activity, identifying institutional-sized trades that may indicate smart money positioning. The data is useful for:

- **Sentiment analysis**: Understand whether big money is bullish or bearish on specific stocks/sectors
- **Trade ideas**: Follow large institutional bets
- **Market intelligence**: Identify unusual options activity before price moves

## Features

- **Smart 5-day lookback**: Uses NYSE trading calendar to skip weekends and holidays
- **Dynamic thresholds**: Automatically adjusts premium thresholds per ticker to capture 5-10 top trades
- **Sweep detection**: Identifies rapid multi-leg orders that indicate aggressive positioning
- **Sector aggregation**: Breaks down sentiment by GICS sector
- **Rate limiting**: Respects Alpaca API limits (200 req/min)

## Output Files

### `options_whale_summary.json`
Aggregate summary data including:
- Overall market sentiment (bullish/bearish)
- Sector-by-sector breakdown with detailed metrics
- DTE (days to expiration) distribution
- Sweeps summary
- Tier breakdown (notable → headline whale)

### `options_whale_trades.json`
Per-ticker whale trades with:
- Full trade details (contract, strike, expiration, premium, etc.)
- Sweep identification flags
- Ticker-level sentiment summaries

## Configuration

All settings are in `config.yml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `lookback_trading_days` | 5 | Number of NYSE trading days to look back |
| `minimum_threshold` | $100,000 | Minimum premium to qualify as whale trade |
| `target_max` | 10 | Target max trades per ticker before stepping up threshold |
| `hard_max` | 20 | Absolute max trades to keep per ticker |
| `max_requests_per_minute` | 180 | API rate limit (buffer below 200) |

### Dynamic Threshold Tiers

The collector steps through these thresholds until a ticker has ≤10 qualifying trades:

```
$100K → $250K → $500K → $1M → $2M → $5M → $10M → $25M → $50M → $100M → $250M → $500M → $1B
```

Mega-cap tickers (SPY, QQQ, AAPL, MSFT, etc.) have 2x multiplier applied.

## Environment Variables

The following environment variables must be set:

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API Key ID |
| `ALPACA_API_SECRET` | Alpaca API Secret Key |

## Usage

### Full S&P 500 Scan
```bash
python fetch_options_whales.py
```

### Test Mode (5 tickers)
```bash
python fetch_options_whales.py --test
```

### Custom Tickers
```bash
python fetch_options_whales.py --tickers AAPL,MSFT,NVDA,TSLA
```

### Custom Output Directory
```bash
python fetch_options_whales.py --output-dir /path/to/output
```

## Dependencies

- `requests`: HTTP requests to Alpaca API
- `pandas`: Data manipulation
- `pandas_market_calendars`: NYSE trading calendar for accurate day counting
- `pyyaml`: Configuration file parsing

Install via:
```bash
pip install requests pandas pandas_market_calendars pyyaml
```

## GitHub Actions Workflow

The collector runs daily at 9 PM ET via GitHub Actions. Workflow file should be added to `.github/workflows/`.

### Required Secrets

Add these secrets to the deanfi-collectors repository:

- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`

## Trade Classification

### Tier Labels

| Tier | Premium Range | Emoji | Description |
|------|---------------|-------|-------------|
| Notable | $10K - $50K | 📊 | Worth watching |
| Unusual | $50K - $100K | 👀 | Notable activity |
| Whale | $100K - $250K | 💰 | Significant trade |
| Strong Whale | $250K - $1M | 🐋 | Large conviction bet |
| Headline | $1M+ | 🔥 | Major institutional activity |

*Thresholds are adjusted by ticker size (mega caps require higher premiums).*

### Moneyness

- **OTM (Out of the Money)**: >2% away from stock price - the primary focus
- **ATM (At the Money)**: Within ±2% of stock price - used for sweep detection
- **ITM (In the Money)**: Excluded (often hedges/stock replacement)

### Sentiment

- **BULLISH 🟢**: Call buying - betting stock goes UP
- **BEARISH 🔴**: Put buying - betting stock goes DOWN
- **Call/Put Ratio**: >1 = bullish bias, <1 = bearish bias

## Sweep Detection

Sweeps are detected when 3+ trades occur within 60 seconds on the same underlying. This often indicates an institution aggressively filling a large order across multiple exchanges/strikes.

Sweep trades are:
1. Listed in the `sweeps` section of the trades JSON
2. Flagged with `is_sweep: true` and `sweep_id` on individual trades

## API Rate Limiting

Alpaca's free tier allows 200 requests/minute. The collector:
- Limits to 180 req/min (with buffer)
- Adds 0.35s delay between ticker scans
- Automatically waits and retries on 429 errors
- Batches options trades requests (100 symbols max)

Full S&P 500 scan typically takes 15-20 minutes.

## File Structure

```
optionswhales/
├── config.yml                 # Configuration
├── fetch_options_whales.py    # Main collector script
├── utils.py                   # Helper functions
└── README.md                  # This file
```

## Related Collectors

- `analysttrends/` - Analyst recommendations for S&P 500
- `whaletrades/` - (Future) Stock whale trades

## Troubleshooting

### "Missing API keys" error
Ensure environment variables are set:
```bash
export ALPACA_API_KEY="your-key-id"
export ALPACA_API_SECRET="your-secret-key"
```

### Rate limit errors
The collector handles these automatically with retry logic. If persistent, check that only one instance is running.

### No trades found
- Check if market was open during lookback period
- Verify API keys have options data access
- Try with `--test` flag to verify connectivity

## License

See repository LICENSE file.
