"""
Fetch Historical Moving Average Percentage for S&P 500

Tracks the percentage of S&P 500 stocks above their moving averages over time.

Calculates daily:
- % of stocks above 50-day moving average (intermediate trend strength)
- % of stocks above 200-day moving average (long-term trend strength)

This indicator helps identify:
- Market breadth strength (>70% = strong, <30% = weak)
- Overbought/oversold conditions
- Trend exhaustion or new trend starts
- Confirmation of index movements

Data source: Yahoo Finance (yfinance)
Output: ma_percentage_historical.json
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


def calculate_ma_percentages_historical(close_prices, ma_periods):
    """
    Calculate historical percentage of stocks above moving averages.
    
    Args:
        close_prices: DataFrame with close prices for all tickers
        ma_periods: List of MA periods to calculate (e.g., [50, 200])
        
    Returns:
        DataFrame with daily MA percentage values
    """
    print(f"Calculating historical MA percentages for periods: {ma_periods}...", file=sys.stderr)
    
    results = []
    
    # For each trading day
    for date in close_prices.index:
        # Get data up to this date
        data_up_to_date = close_prices.loc[:date]
        
        # Skip if we don't have enough data for the longest MA
        if len(data_up_to_date) < max(ma_periods):
            continue
        
        day_result = {'date': date}
        
        # Calculate for each MA period
        for period in ma_periods:
            # Calculate moving average for each stock
            ma = data_up_to_date.rolling(window=period).mean()
            
            # Get the latest price and MA for each stock
            latest_price = data_up_to_date.iloc[-1]
            latest_ma = ma.iloc[-1]
            
            # Count stocks above their MA
            above_ma = latest_price > latest_ma
            num_above = above_ma.sum()
            total_stocks = latest_price.notna().sum()
            
            # Calculate percentage
            pct_above = (num_above / total_stocks * 100) if total_stocks > 0 else 0
            
            day_result[f'ma_{period}'] = {
                'count_above': int(num_above),
                'total_stocks': int(total_stocks),
                'percentage': round(pct_above, 2)
            }
        
        results.append(day_result)
    
    return pd.DataFrame(results)


def calculate_statistics(ma_data, ma_periods):
    """
    Calculate summary statistics for MA percentages.
    
    Args:
        ma_data: DataFrame with MA percentage data
        ma_periods: List of MA periods
        
    Returns:
        Dictionary with statistics for each MA period
    """
    stats = {}
    
    for period in ma_periods:
        pct_series = ma_data[f'ma_{period}'].apply(lambda x: x['percentage'])
        
        # Current value
        current_pct = float(pct_series.iloc[-1])
        
        # Calculate changes
        change_5d = float(pct_series.iloc[-1] - pct_series.iloc[-6]) if len(pct_series) >= 6 else None
        change_20d = float(pct_series.iloc[-1] - pct_series.iloc[-21]) if len(pct_series) >= 21 else None
        change_60d = float(pct_series.iloc[-1] - pct_series.iloc[-61]) if len(pct_series) >= 61 else None
        
        # Determine market condition
        if current_pct >= 70:
            condition = "Strong (most stocks in uptrend)"
        elif current_pct >= 50:
            condition = "Moderate (mixed market)"
        elif current_pct >= 30:
            condition = "Weak (more stocks in downtrend)"
        else:
            condition = "Very Weak (most stocks in downtrend)"
        
        # Calculate extremes
        min_pct = float(pct_series.min())
        max_pct = float(pct_series.max())
        avg_pct = float(pct_series.mean())
        
        # Recent trend
        if change_20d is not None:
            if change_20d > 5:
                trend = "Improving (breadth expanding)"
            elif change_20d < -5:
                trend = "Deteriorating (breadth contracting)"
            else:
                trend = "Stable"
        else:
            trend = "Insufficient data"
        
        stats[f'{period}_day_ma'] = {
            'current_percentage': round(current_pct, 2),
            'market_condition': condition,
            'trend_20d': trend,
            'change_5_days': round(change_5d, 2) if change_5d is not None else None,
            'change_20_days': round(change_20d, 2) if change_20d is not None else None,
            'change_60_days': round(change_60d, 2) if change_60d is not None else None,
            'min_percentage': round(min_pct, 2),
            'max_percentage': round(max_pct, 2),
            'average_percentage': round(avg_pct, 2)
        }
    
    return stats



def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    """Main execution function."""
    # Load configuration
    config = load_config()
    ma_periods = config['moving_averages']
    
    # Fetch S&P 500 tickers
    print("Fetching S&P 500 universe...", file=sys.stderr)
    tickers = fetch_spx_tickers()
    
    # Download market data
    close_prices = download_market_data(tickers, period=config['download_period'], cache_dir=args.cache_dir)
    
    # Calculate MA percentages
    ma_data = calculate_ma_percentages_historical(close_prices, ma_periods)
    
    # Calculate statistics
    print("Calculating statistics...", file=sys.stderr)
    stats = calculate_statistics(ma_data, ma_periods)
    
    # Convert DataFrame to list of dictionaries for JSON
    historical_data = []
    for _, row in ma_data.iterrows():
        day_data = {
            'date': row['date'].strftime('%Y-%m-%d')
        }
        
        # Add data for each MA period
        for period in ma_periods:
            ma_info = row[f'ma_{period}']
            day_data[f'ma_{period}'] = {
                'count_above': ma_info['count_above'],
                'percentage_above': ma_info['percentage']
            }
        
        historical_data.append(day_data)
    
    # Build output JSON structure
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'data_source': config['data_source'],
            'universe': config['universe'],
            'total_stocks': len(tickers),
            'period': config['download_period'],
            'moving_average_periods': ma_periods,
            'description': 'Historical percentage of S&P 500 stocks above their moving averages',
            'interpretation': {
                'above_70_percent': 'Strong market with broad participation - most stocks in uptrend',
                'above_50_percent': 'Moderate market - slight bullish bias',
                'below_50_percent': 'Weak market - more stocks in downtrend than uptrend',
                'below_30_percent': 'Very weak market - most stocks in downtrend, potential oversold',
                '20_day_ma': 'Measures short-term trend strength (1 month)',
                '50_day_ma': 'Measures intermediate-term trend strength (2-3 months)',
                '200_day_ma': 'Measures long-term trend strength (bull vs bear market)'
            }
        },
        'field_descriptions': {
            'date': 'Trading date (YYYY-MM-DD)',
            'ma_20': 'Data for 20-day moving average analysis',
            'ma_50': 'Data for 50-day moving average analysis',
            'ma_200': 'Data for 200-day moving average analysis',
            'count_above': 'Number of stocks trading above their moving average',
            'percentage_above': 'Percentage of stocks trading above their moving average',
            'statistics': 'Summary statistics and trend analysis'
        },
        'statistics': stats,
        'data': historical_data
    }
    
    # Save to JSON file
    output_file = Path(__file__).parent / config['output_files']['ma_percentage_historical']
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Historical MA percentages saved to {output_file}", file=sys.stderr)
    print(f"  Period: {historical_data[0]['date']} to {historical_data[-1]['date']}", file=sys.stderr)
    print(f"  Days tracked: {len(historical_data)}", file=sys.stderr)
    
    for period in ma_periods:
        period_stats = stats[f'{period}_day_ma']
        print(f"\n  {period}-day MA:", file=sys.stderr)
        print(f"    Current: {period_stats['current_percentage']}%", file=sys.stderr)
        print(f"    Condition: {period_stats['market_condition']}", file=sys.stderr)
        print(f"    Trend: {period_stats['trend_20d']}", file=sys.stderr)


if __name__ == "__main__":
    args = parse_args()
    main()
