"""
Fetch Daily Market Breadth Metrics for S&P 500

Calculates comprehensive market breadth indicators including:
- Advances/Declines (number of stocks up/down)
- Advancing/Declining Volume
- 52-week highs/lows percentage
- Percentage of stocks above 50-day and 200-day moving averages

Data source: Yahoo Finance (yfinance)
Output: daily_breadth.json
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
import time


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
        DataFrame with OHLCV data for all tickers
    """
    # Use cache if directory provided, otherwise direct download
    if cache_dir:
        fetcher = CachedDataFetcher(cache_dir=cache_dir)
        data = fetcher.fetch_prices(
            tickers=tickers,
            period=period,
            cache_name="spx_daily_breadth"
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
            print(f"✓ Successfully downloaded data for {len(tickers)} stocks", file=sys.stderr)
        except Exception as e:
            print(f"✗ Error downloading data: {e}", file=sys.stderr)
            raise
    
    return data


def load_latest_ad_line():
    """
    Load the latest cumulative A/D line value from the historical file.
    Looks in both local directory and data repository.
    
    Returns:
        Tuple of (ad_line_value, change_5d, change_20d) or (None, None, None) if file not found
    """
    # Try multiple potential locations
    potential_paths = [
        Path(__file__).parent / 'ad_line_historical.json',  # Local directory
        Path(__file__).parent.parent.parent / 'deanfi-data' / 'advance-decline' / 'ad_line_historical.json',  # Data repo
    ]
    
    for ad_line_file in potential_paths:
        try:
            if ad_line_file.exists():
                with open(ad_line_file, 'r') as f:
                    ad_data = json.load(f)
                    stats = ad_data.get('statistics', {})
                    ad_value = stats.get('current_value')
                    if ad_value is not None:
                        print(f"✓ Loaded A/D line from {ad_line_file}", file=sys.stderr)
                        return (
                            ad_value,
                            stats.get('change_5_days'),
                            stats.get('change_20_days')
                        )
        except Exception as e:
            print(f"Warning: Could not load from {ad_line_file}: {e}", file=sys.stderr)
            continue
    
    print("Warning: A/D line historical file not found in any location", file=sys.stderr)
    return None, None, None


def calculate_daily_breadth(data, config):
    """
    Calculate all daily breadth metrics.
    
    Args:
        data: DataFrame with OHLCV data
        config: Configuration dictionary
        
    Returns:
        Dictionary with all breadth metrics
    """
    close_prices = data['Close']
    volume = data['Volume']
    high_prices = data['High']
    low_prices = data['Low']
    
    # Get the latest two trading days for comparison
    latest_close = close_prices.iloc[-1]
    prev_close = close_prices.iloc[-2]
    latest_volume = volume.iloc[-1]
    
    # Calculate daily price changes
    daily_change = latest_close - prev_close
    pct_change = (daily_change / prev_close) * 100
    
    # --- Advances/Declines ---
    advancing_stocks = daily_change > 0
    declining_stocks = daily_change < 0
    unchanged_stocks = daily_change == 0
    
    advances = int(advancing_stocks.sum())
    declines = int(declining_stocks.sum())
    unchanged = int(unchanged_stocks.sum())
    
    # --- Volume Metrics ---
    advancing_volume = int(latest_volume[advancing_stocks].sum())
    declining_volume = int(latest_volume[declining_stocks].sum())
    total_volume = int(latest_volume.sum())
    
    # --- 52-Week High/Low Analysis ---
    # Calculate 52-week (252 trading days) rolling high/low
    high_52w = high_prices.rolling(window=min(252, len(high_prices))).max()
    low_52w = low_prices.rolling(window=min(252, len(low_prices))).min()
    
    latest_high_52w = high_52w.iloc[-1]
    latest_low_52w = low_52w.iloc[-1]
    
    # Stocks near 52-week high (within threshold)
    high_threshold = config['new_high_threshold']
    low_threshold = config['new_low_threshold']
    
    near_52w_high = (latest_close / latest_high_52w) >= high_threshold
    near_52w_low = (latest_close / latest_low_52w) <= low_threshold
    
    num_near_high = int(near_52w_high.sum())
    num_near_low = int(near_52w_low.sum())
    
    # --- Moving Average Analysis ---
    ma_20 = close_prices.rolling(window=20).mean()
    ma_50 = close_prices.rolling(window=50).mean()
    ma_200 = close_prices.rolling(window=200).mean()
    
    latest_ma_20 = ma_20.iloc[-1]
    latest_ma_50 = ma_50.iloc[-1]
    latest_ma_200 = ma_200.iloc[-1]
    
    above_ma_20 = latest_close > latest_ma_20
    above_ma_50 = latest_close > latest_ma_50
    above_ma_200 = latest_close > latest_ma_200
    
    num_above_ma_20 = int(above_ma_20.sum())
    num_above_ma_50 = int(above_ma_50.sum())
    num_above_ma_200 = int(above_ma_200.sum())
    
    total_stocks = len(latest_close.dropna())
    
    # Calculate percentages
    pct_above_ma_20 = (num_above_ma_20 / total_stocks * 100) if total_stocks > 0 else 0
    pct_above_ma_50 = (num_above_ma_50 / total_stocks * 100) if total_stocks > 0 else 0
    pct_above_ma_200 = (num_above_ma_200 / total_stocks * 100) if total_stocks > 0 else 0
    pct_near_52w_high = (num_near_high / total_stocks * 100) if total_stocks > 0 else 0
    pct_near_52w_low = (num_near_low / total_stocks * 100) if total_stocks > 0 else 0
    
    # Get the latest trading date
    latest_date = close_prices.index[-1].strftime('%Y-%m-%d')
    
    # Load cumulative A/D line value from historical data
    ad_line_value, ad_line_change_5d, ad_line_change_20d = load_latest_ad_line()
    
    # Build advances_declines object
    advances_declines = {
        'advances': advances,
        'declines': declines,
        'unchanged': unchanged,
        'total_stocks': total_stocks,
        'advance_decline_ratio': round(advances / declines, 3) if declines > 0 else None,
        'advance_percentage': round(advances / total_stocks * 100, 2) if total_stocks > 0 else 0,
        'interpretation': 'Advances > Declines suggests broad market strength'
    }
    
    # Add cumulative A/D line if available
    if ad_line_value is not None:
        advances_declines['cumulative_ad_line'] = {
            'value': round(ad_line_value, 1),
            'change_5_days': round(ad_line_change_5d, 1) if ad_line_change_5d is not None else None,
            'change_20_days': round(ad_line_change_20d, 1) if ad_line_change_20d is not None else None,
            'interpretation': 'Running total showing cumulative market participation over time'
        }
    
    return {
        'date': latest_date,
        'advances_declines': advances_declines,
        'volume_metrics': {
            'advancing_volume': advancing_volume,
            'declining_volume': declining_volume,
            'total_volume': total_volume,
            'volume_ratio': round(advancing_volume / declining_volume, 3) if declining_volume > 0 else None,
            'advancing_volume_pct': round(advancing_volume / total_volume * 100, 2) if total_volume > 0 else 0,
            'interpretation': 'Volume ratio > 1 means more volume in advancing stocks (bullish)'
        },
        'new_highs_lows': {
            'stocks_near_52w_high': num_near_high,
            'stocks_near_52w_low': num_near_low,
            'pct_near_52w_high': round(pct_near_52w_high, 2),
            'pct_near_52w_low': round(pct_near_52w_low, 2),
            'high_low_ratio': round(num_near_high / num_near_low, 3) if num_near_low > 0 else None,
            'threshold_note': f'Near high: within {(1-high_threshold)*100:.0f}%, Near low: within {(low_threshold-1)*100:.0f}%',
            'interpretation': 'More new highs than lows indicates strong market leadership'
        },
        'moving_averages': {
            'above_20_day_ma': {
                'count': num_above_ma_20,
                'percentage': round(pct_above_ma_20, 2),
                'interpretation': '>70% = strong short-term trend, <30% = weak short-term trend'
            },
            'above_50_day_ma': {
                'count': num_above_ma_50,
                'percentage': round(pct_above_ma_50, 2),
                'interpretation': '>70% = strong intermediate trend, <30% = weak trend'
            },
            'above_200_day_ma': {
                'count': num_above_ma_200,
                'percentage': round(pct_above_ma_200, 2),
                'interpretation': '>70% = strong long-term trend, <30% = weak trend'
            }
        }
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
    
    # Calculate breadth metrics
    print("Calculating breadth metrics...", file=sys.stderr)
    breadth_metrics = calculate_daily_breadth(data, config)
    
    # Build output JSON structure
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'data_source': config['data_source'],
            'universe': config['universe'],
            'total_stocks_analyzed': len(tickers),
            'description': 'Daily market breadth indicators for S&P 500 constituents',
            'calculation_note': 'All metrics calculated using previous close as baseline'
        },
        'field_descriptions': {
            'date': 'Trading date for the breadth data (YYYY-MM-DD)',
            'advances': 'Number of stocks that closed higher than previous close',
            'declines': 'Number of stocks that closed lower than previous close',
            'unchanged': 'Number of stocks with no price change',
            'advance_decline_ratio': 'Ratio of advancing to declining stocks (advances/declines)',
            'cumulative_ad_line': 'Cumulative advance-decline line (running total of net advances over time)',
            'advancing_volume': 'Total volume of stocks that advanced',
            'declining_volume': 'Total volume of stocks that declined',
            'volume_ratio': 'Ratio of advancing volume to declining volume',
            'stocks_near_52w_high': 'Number of stocks within 1% of their 52-week high',
            'stocks_near_52w_low': 'Number of stocks within 1% of their 52-week low',
            'above_20_day_ma': 'Number and percentage of stocks trading above their 20-day moving average',
            'above_50_day_ma': 'Number and percentage of stocks trading above their 50-day moving average',
            'above_200_day_ma': 'Number and percentage of stocks trading above their 200-day moving average'
        },
        'data': breadth_metrics
    }
    
    # Save to JSON file
    output_file = Path(__file__).parent / config['output_files']['daily_breadth']
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Daily breadth metrics saved to {output_file}", file=sys.stderr)
    print(f"  Date: {breadth_metrics['date']}", file=sys.stderr)
    print(f"  Advances: {breadth_metrics['advances_declines']['advances']}", file=sys.stderr)
    print(f"  Declines: {breadth_metrics['advances_declines']['declines']}", file=sys.stderr)
    print(f"  A/D Ratio: {breadth_metrics['advances_declines']['advance_decline_ratio']}", file=sys.stderr)
    print(f"  Above 20-day MA: {breadth_metrics['moving_averages']['above_20_day_ma']['percentage']}%", file=sys.stderr)
    print(f"  Above 50-day MA: {breadth_metrics['moving_averages']['above_50_day_ma']['percentage']}%", file=sys.stderr)
    print(f"  Above 200-day MA: {breadth_metrics['moving_averages']['above_200_day_ma']['percentage']}%", file=sys.stderr)


if __name__ == "__main__":
    args = parse_args()
    main()
