"""
Fetch Price vs Moving Average Mean Reversion Data

Calculates price distance from moving averages for mean reversion analysis:
- 20-day MA (short-term trend)
- 50-day MA (intermediate trend)  
- 200-day MA (long-term trend)

For each MA, calculates:
- Simple distance (points)
- Percentage distance
- Z-score (statistical significance)

Outputs:
- price_vs_ma_snapshot.json (current values)
- price_vs_ma_historical.json (504-day history)

Data source: Yahoo Finance (yfinance)
Author: DeanFinancials
"""

import yfinance as yf
import pandas as pd
import sys
import argparse
import yaml
from pathlib import Path
from datetime import datetime

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.cache_manager import CachedDataFetcher

from utils import (
    calculate_sma,
    calculate_all_mas,
    calculate_all_price_vs_ma_metrics,
    determine_signal,
    determine_trend_alignment,
    safe_float,
    format_timestamp,
    format_date,
    save_json,
    create_metadata,
    validate_sufficient_data,
    get_data_quality_status
)

# Get script directory
SCRIPT_DIR = Path(__file__).parent

# Load configuration
with open(SCRIPT_DIR / 'config.yml', 'r') as f:
    config = yaml.safe_load(f)

INDICES = config['indices']
MA_PERIODS = [
    config['settings']['ma_periods']['short'],
    config['settings']['ma_periods']['medium'],
    config['settings']['ma_periods']['long']
]
HISTORICAL_DAYS = config['settings']['historical_days']
FETCH_DAYS = config['settings']['fetch_days']
WARMUP_DAYS = config['settings']['warmup_days']
ZSCORE_LOOKBACK = config['settings']['zscore_lookback']


def fetch_index_data(symbol: str, period: str = "5y", cache_dir: str = None) -> pd.DataFrame:
    """
    Fetch historical data for an ETF with optional caching.
    
    Args:
        symbol: ETF symbol (e.g., SPY, QQQ, IWM)
        period: Data period (default: 5y to ensure enough data for z-scores)
        cache_dir: Optional cache directory for parquet files
    
    Returns:
        DataFrame with OHLCV data
    """
    # Use caching if cache_dir provided
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        
        fetcher = CachedDataFetcher(cache_dir=str(cache_dir_path))
        df = fetcher.fetch_prices(
            tickers=[symbol],
            period=period,
            cache_name="meanreversion_price_vs_ma"
        )
        
        if symbol in df.columns:
            result = df[symbol].to_frame()
            result.columns = pd.MultiIndex.from_product([[symbol], ['Close']])
            # For ETFs, yfinance returns simple dataframe, flatten it
            if len(result.columns.levels) > 1:
                result = result.droplevel(0, axis=1)
            return result.tail(FETCH_DAYS)
    
    # Fallback to direct yfinance
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    
    # Ensure we have enough days for z-score calculation
    if len(df) < FETCH_DAYS:
        print(f"Warning: Only {len(df)} days available for {symbol}, need {FETCH_DAYS}", file=sys.stderr)
    
    # Keep the most recent FETCH_DAYS (includes extra for z-score calculation)
    df = df.tail(FETCH_DAYS)
    
    return df


def calculate_price_vs_ma_for_index(
    symbol: str,
    name: str,
    description: str,
    market_segment: str,
    tracks_index: str,
    df: pd.DataFrame
) -> dict:
    """
    Calculate all price vs MA metrics for a single ETF.
    
    Args:
        symbol: ETF symbol
        name: ETF name
        description: ETF description
        market_segment: Market segment
        tracks_index: Index that this ETF tracks
        df: DataFrame with price data
    
    Returns:
        Dictionary with snapshot and historical data
    """
    prices = df['Close']
    
    # Calculate all MAs
    mas = calculate_all_mas(prices, MA_PERIODS)
    
    # Calculate metrics for each MA period
    all_metrics = {}
    for period in MA_PERIODS:
        ma = mas[f'ma_{period}']
        metrics_df = calculate_all_price_vs_ma_metrics(
            prices,
            ma,
            period,
            ZSCORE_LOOKBACK
        )
        all_metrics[period] = metrics_df
    
    # Get current (latest) values for snapshot
    latest_date = prices.index[-1]
    latest_price = prices.iloc[-1]
    
    snapshot = {
        'symbol': symbol,
        'name': name,
        'description': description,
        'market_segment': market_segment,
        'tracks_index': tracks_index,
        'date': format_date(latest_date),
        'current_price': safe_float(latest_price),
        'moving_averages': {},
        'metrics_by_ma': {}
    }
    
    # Add MA values and metrics to snapshot
    for period in MA_PERIODS:
        ma_value = mas[f'ma_{period}'].iloc[-1]
        snapshot['moving_averages'][f'ma_{period}'] = safe_float(ma_value)
        
        metrics = all_metrics[period]
        latest_metrics = {
            'distance': safe_float(metrics['distance'].iloc[-1]),
            'distance_percent': safe_float(metrics['distance_percent'].iloc[-1]),
            'zscore': safe_float(metrics['zscore'].iloc[-1])
        }
        
        # Add signal interpretation
        zscore_val = metrics['zscore'].iloc[-1]
        latest_metrics['signal'] = determine_signal(zscore_val)
        
        snapshot['metrics_by_ma'][f'ma_{period}'] = latest_metrics
    
    # Add trend alignment
    ma_20_val = mas[f'ma_20'].iloc[-1]
    ma_50_val = mas[f'ma_50'].iloc[-1]
    ma_200_val = mas[f'ma_200'].iloc[-1]
    snapshot['trend_alignment'] = determine_trend_alignment(ma_20_val, ma_50_val, ma_200_val)
    
    # Build historical data (calculate on all data, then trim to HISTORICAL_DAYS)
    historical = []
    for i in range(len(prices)):
        date = prices.index[i]
        price = prices.iloc[i]
        
        record = {
            'date': format_date(date),
            'price': safe_float(price),
            'moving_averages': {},
            'metrics': {}
        }
        
        # Add MA values and metrics for each period
        for period in MA_PERIODS:
            ma_val = mas[f'ma_{period}'].iloc[i]
            record['moving_averages'][f'ma_{period}'] = safe_float(ma_val)
            
            metrics = all_metrics[period]
            record['metrics'][f'ma_{period}'] = {
                'distance': safe_float(metrics['distance'].iloc[i]),
                'distance_percent': safe_float(metrics['distance_percent'].iloc[i]),
                'zscore': safe_float(metrics['zscore'].iloc[i])
            }
        
        historical.append(record)
    
    # Trim historical data to only output HISTORICAL_DAYS with valid z-scores
    # Skip the warmup period (200 days for MA + 252 days for z-score calculation)
    # Then take HISTORICAL_DAYS from there
    start_idx = WARMUP_DAYS
    end_idx = start_idx + HISTORICAL_DAYS
    historical = historical[start_idx:end_idx]
    
    # Data quality info
    data_quality = get_data_quality_status(df, HISTORICAL_DAYS)
    
    return {
        'snapshot': snapshot,
        'historical': historical,
        'data_quality': data_quality
    }


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Fetch price vs MA mean reversion data')
    parser.add_argument('--cache-dir', type=str, help='Cache directory for parquet files')
    args = parser.parse_args()
    
    print("=" * 80, file=sys.stderr)
    print("PRICE VS MOVING AVERAGE MEAN REVERSION COLLECTOR", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Tracking {len(INDICES)} ETFs", file=sys.stderr)
    print(f"MA periods: {MA_PERIODS}", file=sys.stderr)
    print(f"Historical days: {HISTORICAL_DAYS}", file=sys.stderr)
    print(f"Z-score lookback: {ZSCORE_LOOKBACK}", file=sys.stderr)
    if args.cache_dir:
        print(f"Using cache: {args.cache_dir}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    
    # Prepare output structures
    snapshot_data = {
        '_README': {
            'title': 'Price vs Moving Average - Mean Reversion Snapshot',
            'description': 'Current price distance from key moving averages for major US ETFs',
            'purpose': 'Identify overbought/oversold conditions and potential mean reversion opportunities',
            'update_frequency': 'Every 15 minutes during market hours',
            'indices_tracked': [idx['symbol'] for idx in INDICES],
            'moving_averages': {
                'ma_20': '20-day SMA (short-term trend, ~1 month)',
                'ma_50': '50-day SMA (intermediate trend, ~2.5 months)',
                'ma_200': '200-day SMA (long-term trend, ~1 year)'
            },
            'metrics_explained': {
                'distance': {
                    'description': 'Point distance between current price and MA',
                    'formula': 'current_price - ma_value',
                    'interpretation': 'Positive = above MA (bullish), Negative = below MA (bearish)'
                },
                'distance_percent': {
                    'description': 'Percentage distance from MA',
                    'formula': '(current_price - ma_value) / ma_value * 100',
                    'interpretation': {
                        '>5%': 'Significantly overbought',
                        '2% to 5%': 'Moderately overbought',
                        '-2% to 2%': 'Normal range',
                        '-5% to -2%': 'Moderately oversold',
                        '<-5%': 'Significantly oversold'
                    }
                },
                'zscore': {
                    'description': 'Statistical z-score of price distance from MA',
                    'formula': '(current_price - ma) / std_dev(price - ma)',
                    'lookback_period': f'{ZSCORE_LOOKBACK} days',
                    'interpretation': {
                        '>2': 'Statistically overbought (>95th percentile) - Strong mean reversion signal',
                        '1 to 2': 'Moderately overbought',
                        '-1 to 1': 'Normal statistical range',
                        '-2 to -1': 'Moderately oversold',
                        '<-2': 'Statistically oversold (<5th percentile) - Strong mean reversion signal'
                    },
                    'usage': 'Institutional standard for normalized mean reversion signals'
                }
            },
            'signal_types': {
                'extremely_overbought': 'Z-score > 2 (potential reversal down)',
                'moderately_overbought': 'Z-score 1 to 2',
                'normal_range': 'Z-score -1 to 1',
                'moderately_oversold': 'Z-score -2 to -1',
                'extremely_oversold': 'Z-score < -2 (potential reversal up)',
                'insufficient_data': 'Not enough data for calculation'
            },
            'trend_alignment': {
                'strong_bullish': '20-day > 50-day > 200-day (all MAs aligned bullish)',
                'moderate_bullish': '20-day > 50-day (short above medium)',
                'strong_bearish': '20-day < 50-day < 200-day (all MAs aligned bearish)',
                'moderate_bearish': '20-day < 50-day (short below medium)',
                'mixed': 'No clear alignment'
            },
            'trading_applications': {
                'mean_reversion': 'Use extreme z-scores as contrarian entry signals',
                'trend_filter': 'Only trade mean reversion in direction of 200-day MA',
                'overbought_oversold': 'Distance >5% or z-score >2 indicates stretched conditions'
            }
        },
        'metadata': create_metadata(
            etfs_count=len(INDICES),
            description='Price distance from moving averages for mean reversion analysis'
        ),
        'indices': {}
    }
    
    historical_data = {
        '_README': {
            'title': 'Price vs Moving Average - Historical Data',
            'description': f'{HISTORICAL_DAYS}-day historical price vs MA metrics',
            'purpose': 'Analyze historical mean reversion patterns and calculate z-scores',
            'trading_days': HISTORICAL_DAYS,
            'usage': {
                'backtesting': 'Test mean reversion strategies using historical z-scores',
                'pattern_recognition': 'Identify recurring overbought/oversold levels',
                'strategy_optimization': 'Find optimal z-score thresholds for entry/exit'
            }
        },
        'metadata': create_metadata(
            etfs_count=len(INDICES),
            description=f'{HISTORICAL_DAYS}-day history of price vs MA metrics'
        ),
        'settings': {
            'ma_periods': MA_PERIODS,
            'historical_days': HISTORICAL_DAYS,
            'zscore_lookback': ZSCORE_LOOKBACK
        },
        'indices': {}
    }
    
    # Process each ETF
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        name = idx_config['name']
        description = idx_config['description']
        market_segment = idx_config['market_segment']
        tracks_index = idx_config.get('tracks_index', '')
        
        print(f"\nProcessing {symbol} ({name})...", file=sys.stderr)
        
        try:
            # Fetch data (fetch extra for z-score calculation)
            df = fetch_index_data(symbol, period="5y", cache_dir=args.cache_dir)
            print(f"  Retrieved {len(df)} days of data", file=sys.stderr)
            
            # Calculate metrics
            results = calculate_price_vs_ma_for_index(
                symbol, name, description, market_segment, tracks_index, df
            )
            
            # Add to output structures
            snapshot_data['indices'][symbol] = results['snapshot']
            historical_data['indices'][symbol] = {
                'name': name,
                'symbol': symbol,
                'description': description,
                'market_segment': market_segment,
                'tracks_index': tracks_index,
                'data': results['historical'],
                'data_quality': results['data_quality']
            }
            
            # Print latest values
            latest = results['snapshot']
            print(f"  Current price: ${latest['current_price']:.2f}", file=sys.stderr)
            for period in MA_PERIODS:
                ma_val = latest['moving_averages'][f'ma_{period}']
                metrics = latest['metrics_by_ma'][f'ma_{period}']
                print(f"  {period}-day MA: ${ma_val:.2f} | "
                      f"Distance: {metrics['distance_percent']:.2f}% | "
                      f"Z-score: {metrics['zscore']:.2f} | "
                      f"Signal: {metrics['signal']}", file=sys.stderr)
            
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
    
    # Save output files
    output_dir = SCRIPT_DIR / config['settings']['output_dir']
    snapshot_file = output_dir / config['output_files']['price_vs_ma']['snapshot']
    historical_file = output_dir / config['output_files']['price_vs_ma']['historical']
    
    print(f"\nSaving snapshot to {snapshot_file}...", file=sys.stderr)
    save_json(snapshot_data, str(snapshot_file))
    
    print(f"Saving historical data to {historical_file}...", file=sys.stderr)
    save_json(historical_data, str(historical_file))
    
    print("\n" + "=" * 80, file=sys.stderr)
    print("COMPLETE", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Snapshot: {snapshot_file}", file=sys.stderr)
    print(f"Historical: {historical_file}", file=sys.stderr)


if __name__ == '__main__':
    main()
