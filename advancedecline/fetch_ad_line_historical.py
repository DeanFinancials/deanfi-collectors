"""
Fetch Historical Advance-Decline Line for S&P 500

Calculates the cumulative Advance-Decline (A/D) line over the past year.

The A/D line is a cumulative indicator that:
- Adds 1 for each stock that advances on a given day
- Subtracts 1 for each stock that declines
- Running total shows overall market participation

Uses:
- Confirm trends: A/D line should rise with the index in healthy uptrends
- Spot divergences: Index making new highs while A/D line declining = warning
- Measure breadth: Rising A/D line = broad participation

Data source: Yahoo Finance (yfinance)
Output: ad_line_historical.json
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
        DataFrame with close prices for all tickers
    """
    # Use cache if directory provided
    if cache_dir:
        fetcher = CachedDataFetcher(cache_dir=cache_dir)
        data = fetcher.fetch_prices(
            tickers=tickers,
            period=period,
            cache_name="spx_daily_breadth", reuse_within_run=True
        )
        return data['Close'] if not data.empty else data
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
            return data['Close']
        except Exception as e:
            print(f"✗ Error downloading data: {e}", file=sys.stderr)
            raise


def calculate_ad_line_historical(close_prices):
    """
    Calculate historical A/D line from price data.
    
    Args:
        close_prices: DataFrame with close prices for all tickers
        
    Returns:
        DataFrame with daily A/D line values
    """
    print("Calculating historical A/D line...", file=sys.stderr)
    
    # Calculate daily price changes for each stock
    daily_changes = close_prices.pct_change(fill_method=None)
    
    # For each day, count advances minus declines
    # Advances: daily_change > 0
    # Declines: daily_change < 0
    advances_daily = (daily_changes > 0).sum(axis=1)
    declines_daily = (daily_changes < 0).sum(axis=1)
    
    # Daily A/D value is advances - declines
    ad_daily = advances_daily - declines_daily
    
    # Cumulative A/D line
    ad_line = ad_daily.cumsum()
    
    # Create DataFrame with all components
    ad_data = pd.DataFrame({
        'date': close_prices.index,
        'advances': advances_daily.values,
        'declines': declines_daily.values,
        'net_advances': ad_daily.values,
        'ad_line': ad_line.values
    })
    
    # Remove the first row (NaN from pct_change)
    ad_data = ad_data.iloc[1:].reset_index(drop=True)
    
    return ad_data


def calculate_statistics(ad_data):
    """
    Calculate summary statistics for the A/D line.
    
    Args:
        ad_data: DataFrame with A/D line data
        
    Returns:
        Dictionary with statistics
    """
    ad_line = ad_data['ad_line']
    
    # Calculate moving averages of the A/D line
    ad_ma_20 = ad_line.rolling(window=20).mean()
    ad_ma_50 = ad_line.rolling(window=50).mean()
    
    # Current values
    current_ad = float(ad_line.iloc[-1])
    current_ma_20 = float(ad_ma_20.iloc[-1]) if not pd.isna(ad_ma_20.iloc[-1]) else None
    current_ma_50 = float(ad_ma_50.iloc[-1]) if not pd.isna(ad_ma_50.iloc[-1]) else None
    
    # Trend analysis
    change_5d = float(ad_line.iloc[-1] - ad_line.iloc[-6]) if len(ad_line) >= 6 else None
    change_20d = float(ad_line.iloc[-1] - ad_line.iloc[-21]) if len(ad_line) >= 21 else None
    change_60d = float(ad_line.iloc[-1] - ad_line.iloc[-61]) if len(ad_line) >= 61 else None
    
    # Determine trend
    if change_20d is not None:
        if change_20d > 0:
            trend = "Rising (bullish breadth)"
        elif change_20d < 0:
            trend = "Declining (bearish breadth)"
        else:
            trend = "Neutral"
    else:
        trend = "Insufficient data"
    
    return {
        'current_value': round(current_ad, 2),
        'ma_20': round(current_ma_20, 2) if current_ma_20 is not None else None,
        'ma_50': round(current_ma_50, 2) if current_ma_50 is not None else None,
        'change_5_days': round(change_5d, 2) if change_5d is not None else None,
        'change_20_days': round(change_20d, 2) if change_20d is not None else None,
        'change_60_days': round(change_60d, 2) if change_60d is not None else None,
        'trend': trend,
        'min_value': round(float(ad_line.min()), 2),
        'max_value': round(float(ad_line.max()), 2),
        'days_tracked': len(ad_line)
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
    close_prices = download_market_data(tickers, period=config['download_period'], cache_dir=args.cache_dir)
    
    # Calculate A/D line
    ad_data = calculate_ad_line_historical(close_prices)
    
    # Calculate statistics
    print("Calculating statistics...", file=sys.stderr)
    stats = calculate_statistics(ad_data)
    
    # Convert DataFrame to list of dictionaries for JSON
    historical_data = []
    for _, row in ad_data.iterrows():
        historical_data.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'advances': int(row['advances']),
            'declines': int(row['declines']),
            'net_advances': int(row['net_advances']),
            'ad_line': round(float(row['ad_line']), 2)
        })
    
    # Build output JSON structure
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'data_source': config['data_source'],
            'universe': config['universe'],
            'total_stocks': len(tickers),
            'period': config['download_period'],
            'description': 'Historical Advance-Decline Line for S&P 500',
            'calculation_method': 'Cumulative sum of daily (advances - declines)',
            'interpretation': {
                'rising_ad_line': 'Indicates broad market participation and healthy uptrend',
                'declining_ad_line': 'Suggests weakening breadth and potential trend exhaustion',
                'divergence_bullish': 'Index declining but A/D line rising = potential reversal up',
                'divergence_bearish': 'Index rising but A/D line declining = potential reversal down'
            }
        },
        'field_descriptions': {
            'date': 'Trading date (YYYY-MM-DD)',
            'advances': 'Number of stocks that closed higher than previous day',
            'declines': 'Number of stocks that closed lower than previous day',
            'net_advances': 'Daily net advances (advances - declines)',
            'ad_line': 'Cumulative advance-decline line (running total of net_advances)',
            'statistics': 'Summary statistics and trend analysis of the A/D line'
        },
        'statistics': stats,
        'data': historical_data
    }
    
    # Save to JSON file
    output_file = Path(__file__).parent / config['output_files']['ad_line_historical']
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Historical A/D line saved to {output_file}", file=sys.stderr)
    print(f"  Period: {historical_data[0]['date']} to {historical_data[-1]['date']}", file=sys.stderr)
    print(f"  Days tracked: {stats['days_tracked']}", file=sys.stderr)
    print(f"  Current A/D line: {stats['current_value']}", file=sys.stderr)
    print(f"  Trend: {stats['trend']}", file=sys.stderr)
    print(f"  20-day change: {stats['change_20_days']}", file=sys.stderr)


if __name__ == "__main__":
    args = parse_args()
    main()
