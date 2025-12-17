# Stock Whale Collector

Detects large stock trades ("whale trades") for S&P 500 constituents using the Alpaca Markets Stock Trades API. Focuses on identifying institutional activity, particularly dark pool (off-exchange) trades.

## Overview

This collector scans S&P 500 stocks for large trades that indicate institutional positioning. It uses dynamic thresholds to capture significant activity while filtering out noise, and infers trade direction using the Lee-Ready algorithm.

### Key Features

- **Dark Pool Detection**: Identifies trades executed on Exchange D (FINRA ADF / off-exchange)
- **Direction Inference**: Uses Lee-Ready algorithm to determine if trades are buys or sells
- **Dynamic Thresholds**: Automatically adjusts thresholds to capture 5-10 whale trades per ticker
- **High-Confidence Filtering**: Separates trades with ≥80% direction confidence
- **Sector Analysis**: Aggregates sentiment by GICS sector
- **Split Output**: Summary JSON (aggregates) + Trades JSON (per-ticker details)

## Requirements

### Environment Variables

```bash
# Alpaca API credentials (either format works)
export ALPACA_API_KEY="your-api-key"
export ALPACA_API_SECRET="your-api-secret"
# OR
export APCA-API-KEY-ID="your-api-key"
export APCA-API-SECRET-KEY="your-api-secret"
```

### Dependencies

- `requests` - HTTP client for API calls
- `pyyaml` - Configuration file parsing
- `pandas` - Data manipulation
- `pandas_market_calendars` - NYSE trading day calculations

## Usage

```bash
# Full S&P 500 scan
python fetch_stock_whales.py

# Test mode (5 tickers)
python fetch_stock_whales.py --test

# Custom tickers
python fetch_stock_whales.py --tickers AAPL,MSFT,NVDA,TSLA

# Custom output directory
python fetch_stock_whales.py --output-dir /path/to/output

# Quiet mode (no progress output)
python fetch_stock_whales.py --quiet
```

## Configuration

See `config.yml` for all configurable parameters:

### Thresholds

A trade qualifies as a "whale" if it meets **EITHER** condition (OR logic):
- **Shares** ≥ threshold, OR
- **Value** ≥ threshold

| Tier | Shares | Value |
|------|--------|-------|
| 1 (min) | 5,000 | $1,000,000 |
| 2 | 10,000 | $2,500,000 |
| 3 | 25,000 | $5,000,000 |
| 4 | 50,000 | $10,000,000 |
| 5 | 100,000 | $25,000,000 |
| ... | Higher tiers | ... |

### Tier Labels

| Tier | Value Range | Label |
|------|-------------|-------|
| Notable | $1M - $2.5M | 📊 Notable |
| Large | $2.5M - $5M | 🐋 Large |
| Whale | $5M - $10M | 🐋🐋 Whale |
| Mega Whale | $10M+ | 🐋🐋🐋 Mega Whale |

### Lookback Period

- **5 trading days** (excludes weekends and NYSE holidays)
- Uses `pandas_market_calendars` for accurate holiday detection

## Output Files

### `stock_whale_summary.json`

High-level aggregates and sentiment analysis:

```json
{
  "_README": { /* Documentation */ },
  "metadata": {
    "collection_timestamp": "2025-12-17T12:00:00",
    "trading_days": 5,
    "tickers_scanned": 503,
    "total_whale_trades": 450
  },
  "overall_sentiment": {
    "direction": "BULLISH",
    "high_confidence_direction": "BULLISH",
    "buy_value": 5000000000,
    "sell_value": 3000000000,
    "net_value": 2000000000
  },
  "dark_pool_sentiment": {
    "direction": "BULLISH",
    "trade_count": 200,
    "total_value": 4000000000,
    "pct_of_whale_volume": 50.0
  },
  "top_bullish_trades": { /* Top 10 tickers by BUY activity */ },
  "top_bearish_trades": { /* Top 10 tickers by SELL activity */ },
  "sector_sentiment": { /* By GICS sector */ },
  "exchange_breakdown": { /* By exchange code */ }
}
```

### `stock_whale_trades.json`

Per-ticker whale trades with details:

```json
{
  "_README": { /* Documentation */ },
  "metadata": { /* Same as summary */ },
  "by_ticker": {
    "AAPL": {
      "sentiment": "BULLISH",
      "high_confidence_sentiment": "BULLISH",
      "buy_value": 50000000,
      "sell_value": 20000000,
      "dark_pool_count": 5,
      "dark_pool_value": 40000000,
      "trades": [
        {
          "timestamp": "2025-12-17T14:30:00Z",
          "price": 175.50,
          "shares": 50000,
          "value": 8775000,
          "exchange": "D",
          "is_dark_pool": true,
          "direction": "BUY",
          "direction_confidence": 95,
          "tier": "Whale"
        }
      ]
    }
  }
}
```

## Dark Pool Analysis

### What is a Dark Pool?

Dark pools are private exchanges where institutional investors execute large block trades without revealing their orders to the public market. This minimizes market impact and allows large positions to be built or unwound discreetly.

### Exchange Code D

In Alpaca's data feed, Exchange code `D` indicates **FINRA ADF** (Alternative Display Facility), which is where dark pool / off-exchange trades are reported. These trades are typically:

- **Institutional**: Large players like hedge funds, pension funds, mutual funds
- **Block trades**: Larger than typical retail orders
- **Meaningful**: Indicate significant positioning by sophisticated investors

### Interpreting Dark Pool Sentiment

- **High dark pool buy volume**: Institutional accumulation (bullish)
- **High dark pool sell volume**: Institutional distribution (bearish)
- **Dark pool % of whale volume**: How much institutional activity vs. retail/lit exchange

## Direction Inference (Lee-Ready Algorithm)

Trade direction is inferred by comparing the trade price to the bid/ask spread:

| Position | Confidence | Interpretation |
|----------|------------|----------------|
| At/above ASK | 95% | Aggressive BUY (buyer lifted offer) |
| At/below BID | 95% | Aggressive SELL (seller hit bid) |
| Near ASK (70-99%) | 50-95% | Likely BUY |
| Near BID (1-30%) | 50-95% | Likely SELL |
| Midpoint (30-70%) | 50% | Direction unclear |

### High Confidence Threshold

Trades with ≥80% confidence are considered "high confidence" and are aggregated separately in the sentiment calculations.

## Architecture

```
S&P 500 Tickers (via shared/spx_universe.py)
       │
       ▼
fetch_stock_whales.py
       │
       ├─► Alpaca /v2/stocks/{symbol}/trades (trade history)
       └─► Alpaca /v2/stocks/{symbol}/quotes (for direction inference)
       │
       ▼
Dynamic Threshold Selection
(step up until ≤10 trades per ticker)
       │
       ▼
Direction Inference (Lee-Ready)
       │
       ▼
   [Split Output]
       │
       ├─► stock_whale_summary.json (aggregates, sentiment, sectors)
       │
       └─► stock_whale_trades.json (individual trades by ticker)
```

## Related Collectors

- **optionswhales**: Large options trades (OTM) with sweep detection
- **majorindexes**: Market indices and breadth metrics
- **analysttrends**: Analyst recommendations and revisions

## Troubleshooting

### No trades found

- Check API credentials are valid
- Verify market was open during lookback period
- Try with `--test` flag for limited ticker set

### Rate limiting

- Collector respects 180 requests/minute limit
- Will automatically wait if rate limited
- Reduce ticker count or increase `batch_delay` in config

### Missing tickers

- Some tickers may not have trade data available
- BRK.A is skipped (extremely high price, no liquid options)
- Tickers with share class notation (BRK-B → BRK.B) are converted automatically
