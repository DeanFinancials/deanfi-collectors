"""
Fetch Historical 52-Week Highs/Lows Percentage for S&P 500

Tracks the percentage of S&P 500 stocks near their 52-week highs and lows over time.

Calculates daily:
- % of stocks within 1% of their 52-week high (strong leadership)
- % of stocks within 1% of their 52-week low (weak market)
- High/Low ratio (relative strength indicator)

This indicator helps identify:
- Market leadership strength (many stocks at highs = healthy)
- Distribution and selling pressure (many stocks at lows = weakness)
- Divergences (index at highs but few stocks participating)
- Extremes that may signal turning points

Data source: Yahoo Finance (yfinance)
Output: highs_lows_historical.json
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import json
import yaml
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spx_universe import fetch_spx_tickers
from shared.cache_manager import CachedDataFetcher


def load_config():
    """Load configuration from config.yml"""
    config_path = Path(__file__).parent / "config.yml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def download_market_data(tickers, period="1y", cache_dir=None):
    """
    Download historical data for all tickers with caching.
    
    Args:
        tickers: List of ticker symbols
        period: Period for historical data (default: 1y)
        cache_dir: Cache directory path (optional)
        
    Returns:
        DataFrame with high and low prices for all tickers
    """
    # Use cache if directory provided
    if cache_dir:
        fetcher = CachedDataFetcher(cache_dir=cache_dir)
        data = fetcher.fetch_prices(
            tickers=tickers,
            period=period,
            cache_name="spx_daily_breadth", reuse_within_run=True
        )
    else:
        print(f"Downloading {period} of data for {len(tickers)} stocks...", file=sys.stderr)
        try:
            data = yf.download(
                tickers,
                period=period,
                progress=False,
                auto_adjust=True,
                threads=True
            )
            print(f"✓ Successfully downloaded data", file=sys.stderr)
        except Exception as e:
            print(f"✗ Error downloading data: {e}", file=sys.stderr)
            raise
    
    return data


def calculate_highs_lows_historical(data, high_threshold, low_threshold):
    """
    Calculate historical percentage of stocks near 52-week highs and lows.
    
    Args:
        data: DataFrame with OHLCV data
        high_threshold: Percentage threshold for 52-week high (e.g., 0.99 = within 1%)
        low_threshold: Percentage threshold for 52-week low (e.g., 1.01 = within 1%)
        
    Returns:
        DataFrame with daily high/low percentages
    """
    print(f"Calculating historical 52-week highs/lows...", file=sys.stderr)
    
    close_prices = data['Close']
    high_prices = data['High']
    low_prices = data['Low']
    
    results = []
    
    # Calculate minimum lookback needed (use 200 days as minimum for 52-week)
    min_lookback = 200
    
    # For each trading day
    for i, date in enumerate(close_prices.index):
        # Need at least min_lookback days to calculate meaningful 52-week high/low
        if i < min_lookback:
            continue
        
        # Get data up to this date
        data_up_to_date = close_prices.loc[:date]
        high_up_to_date = high_prices.loc[:date]
        low_up_to_date = low_prices.loc[:date]
        
        # Calculate 52-week high/low for each stock
        # Use all available data up to 252 days (1 year), or whatever we have
        lookback_days = min(252, len(high_up_to_date))
        high_52w = high_up_to_date.iloc[-lookback_days:].max()
        low_52w = low_up_to_date.iloc[-lookback_days:].min()
        
        # Current close price
        current_price = data_up_to_date.iloc[-1]
        
        # Count stocks near 52-week high (within threshold)
        near_high = (current_price / high_52w) >= high_threshold
        num_near_high = near_high.sum()
        
        # Count stocks near 52-week low (within threshold)
        near_low = (current_price / low_52w) <= low_threshold
        num_near_low = near_low.sum()
        
        # Total stocks with valid data
        total_stocks = current_price.notna().sum()
        
        # Calculate percentages
        pct_near_high = (num_near_high / total_stocks * 100) if total_stocks > 0 else 0
        pct_near_low = (num_near_low / total_stocks * 100) if total_stocks > 0 else 0
        
        # Calculate ratio
        high_low_ratio = (num_near_high / num_near_low) if num_near_low > 0 else None
        
        results.append({
            'date': date,
            'near_52w_high_count': int(num_near_high),
            'near_52w_high_pct': round(pct_near_high, 2),
            'near_52w_low_count': int(num_near_low),
            'near_52w_low_pct': round(pct_near_low, 2),
            'high_low_ratio': round(high_low_ratio, 3) if high_low_ratio is not None else None,
            'total_stocks': int(total_stocks)
        })
    
    return pd.DataFrame(results)


def calculate_statistics(highs_lows_data):
    """
    Calculate summary statistics for highs/lows percentages.
    
    Args:
        highs_lows_data: DataFrame with highs/lows data
        
    Returns:
        Dictionary with statistics
    """
    # Extract percentage series
    pct_high_series = highs_lows_data['near_52w_high_pct']
    pct_low_series = highs_lows_data['near_52w_low_pct']
    ratio_series = highs_lows_data['high_low_ratio'].dropna()
    
    # Current values
    current_pct_high = float(pct_high_series.iloc[-1])
    current_pct_low = float(pct_low_series.iloc[-1])
    current_ratio = float(ratio_series.iloc[-1]) if len(ratio_series) > 0 and not pd.isna(ratio_series.iloc[-1]) else None
    
    # Changes
    change_5d_high = float(pct_high_series.iloc[-1] - pct_high_series.iloc[-6]) if len(pct_high_series) >= 6 else None
    change_20d_high = float(pct_high_series.iloc[-1] - pct_high_series.iloc[-21]) if len(pct_high_series) >= 21 else None
    
    change_5d_low = float(pct_low_series.iloc[-1] - pct_low_series.iloc[-6]) if len(pct_low_series) >= 6 else None
    change_20d_low = float(pct_low_series.iloc[-1] - pct_low_series.iloc[-21]) if len(pct_low_series) >= 21 else None
    
    # Market condition based on highs/lows
    if current_pct_high > 10 and current_ratio and current_ratio > 2:
        condition = "Strong Leadership (many stocks at highs)"
    elif current_pct_low > 10 and current_ratio and current_ratio < 0.5:
        condition = "Weak Distribution (many stocks at lows)"
    elif current_pct_high > 5 and current_pct_low < 5:
        condition = "Moderate Strength (more highs than lows)"
    elif current_pct_low > 5 and current_pct_high < 5:
        condition = "Moderate Weakness (more lows than highs)"
    else:
        condition = "Neutral (mixed market)"
    
    # Trend analysis
    if change_20d_high is not None and change_20d_low is not None:
        if change_20d_high > 2 and change_20d_low < -2:
            trend = "Improving (more highs, fewer lows)"
        elif change_20d_high < -2 and change_20d_low > 2:
            trend = "Deteriorating (fewer highs, more lows)"
        else:
            trend = "Stable"
    else:
        trend = "Insufficient data"
    
    return {
        'near_52w_high': {
            'current_percentage': round(current_pct_high, 2),
            'change_5_days': round(change_5d_high, 2) if change_5d_high is not None else None,
            'change_20_days': round(change_20d_high, 2) if change_20d_high is not None else None,
            'min_percentage': round(float(pct_high_series.min()), 2),
            'max_percentage': round(float(pct_high_series.max()), 2),
            'average_percentage': round(float(pct_high_series.mean()), 2)
        },
        'near_52w_low': {
            'current_percentage': round(current_pct_low, 2),
            'change_5_days': round(change_5d_low, 2) if change_5d_low is not None else None,
            'change_20_days': round(change_20d_low, 2) if change_20d_low is not None else None,
            'min_percentage': round(float(pct_low_series.min()), 2),
            'max_percentage': round(float(pct_low_series.max()), 2),
            'average_percentage': round(float(pct_low_series.mean()), 2)
        },
        'high_low_ratio': {
            'current': round(current_ratio, 3) if current_ratio is not None else None,
            'average': round(float(ratio_series.mean()), 3) if len(ratio_series) > 0 else None
        },
        'market_condition': condition,
        'trend': trend,
        'days_tracked': len(highs_lows_data)
    }



def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    """Main execution function."""
    # Load configuration
    config = load_config()
    
    # Fetch S&P 500 tickers
    print("Fetching S&P 500 universe...", file=sys.stderr)
    tickers = fetch_spx_tickers()
    
    # Download market data
    data = download_market_data(tickers, period=config['download_period'], cache_dir=args.cache_dir)
    
    # Calculate highs/lows percentages
    highs_lows_data = calculate_highs_lows_historical(
        data,
        config['new_high_threshold'],
        config['new_low_threshold']
    )
    
    # Calculate statistics
    print("Calculating statistics...", file=sys.stderr)
    stats = calculate_statistics(highs_lows_data)
    
    # Convert DataFrame to list of dictionaries for JSON
    historical_data = []
    for _, row in highs_lows_data.iterrows():
        historical_data.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'near_52w_high': {
                'count': int(row['near_52w_high_count']),
                'percentage': float(row['near_52w_high_pct'])
            },
            'near_52w_low': {
                'count': int(row['near_52w_low_count']),
                'percentage': float(row['near_52w_low_pct'])
            },
            'high_low_ratio': float(row['high_low_ratio']) if not pd.isna(row['high_low_ratio']) else None
        })
    
    # Build output JSON structure
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'data_source': config['data_source'],
            'universe': config['universe'],
            'total_stocks': len(tickers),
            'period': config['download_period'],
            'high_threshold': config['new_high_threshold'],
            'low_threshold': config['new_low_threshold'],
            'description': 'Historical percentage of S&P 500 stocks near 52-week highs and lows',
            'interpretation': {
                'high_percentage_near_highs': '>10% of stocks at highs indicates strong leadership and healthy market',
                'high_percentage_near_lows': '>10% of stocks at lows suggests broad weakness and distribution',
                'high_ratio_above_2': 'Strong market with good breadth - more stocks leading higher',
                'low_ratio_below_0.5': 'Weak market with poor breadth - more stocks at lows than highs',
                'extremes': 'Very high readings (>15%) at either extreme can signal potential reversals',
                'divergence': 'Index at new high but few stocks participating = bearish divergence'
            }
        },
        'field_descriptions': {
            'date': 'Trading date (YYYY-MM-DD)',
            'near_52w_high': 'Data for stocks within 1% of their 52-week high',
            'near_52w_low': 'Data for stocks within 1% of their 52-week low',
            'count': 'Number of stocks meeting the criteria',
            'percentage': 'Percentage of S&P 500 stocks meeting the criteria',
            'high_low_ratio': 'Ratio of stocks near highs to stocks near lows (higher = stronger)',
            'statistics': 'Summary statistics and trend analysis'
        },
        'statistics': stats,
        'data': historical_data
    }
    
    # Save to JSON file
    output_file = Path(__file__).parent / config['output_files']['highs_lows_historical']
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Historical 52-week highs/lows saved to {output_file}", file=sys.stderr)
    print(f"  Period: {historical_data[0]['date']} to {historical_data[-1]['date']}", file=sys.stderr)
    print(f"  Days tracked: {stats['days_tracked']}", file=sys.stderr)
    print(f"\n  Near 52-week high:", file=sys.stderr)
    print(f"    Current: {stats['near_52w_high']['current_percentage']}%", file=sys.stderr)
    print(f"    20-day change: {stats['near_52w_high']['change_20_days']}%", file=sys.stderr)
    print(f"\n  Near 52-week low:", file=sys.stderr)
    print(f"    Current: {stats['near_52w_low']['current_percentage']}%", file=sys.stderr)
    print(f"    20-day change: {stats['near_52w_low']['change_20_days']}%", file=sys.stderr)
    print(f"\n  Market condition: {stats['market_condition']}", file=sys.stderr)
    print(f"  Trend: {stats['trend']}", file=sys.stderr)


if __name__ == "__main__":
    args = parse_args()
    main()
