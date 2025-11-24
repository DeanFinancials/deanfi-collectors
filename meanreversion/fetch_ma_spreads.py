"""
Fetch Moving Average Spread Mean Reversion Data

Calculates spread between moving average pairs for mean reversion analysis:
- 20-day vs 50-day MA
- 20-day vs 200-day MA
- 50-day vs 200-day MA

For each MA pair, calculates:
- Simple spread (points)
- Percentage spread
- Z-score (statistical significance)

Outputs:
- ma_spreads_snapshot.json (current values)
- ma_spreads_historical.json (504-day history)

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
    calculate_all_ma_spread_metrics,
    determine_signal,
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
ZSCORE_LOOKBACK = config['settings']['zscore_lookback']

# Define MA pairs to analyze
MA_PAIRS = [
    (20, 50, "short_term_vs_intermediate"),
    (20, 200, "short_term_vs_long_term"),
    (50, 200, "intermediate_vs_long_term")
]


def fetch_index_data(symbol: str, period: str = "2y", cache_dir: str = None) -> pd.DataFrame:
    """
    Fetch historical data for an index with optional caching.
    
    Args:
        symbol: Index symbol (e.g., ^GSPC)
        period: Data period (default: 2y for 504 trading days)
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
            cache_name="meanreversion_ma_spreads"
        )
        
        if symbol in df.columns:
            result = df[symbol].to_frame()
            result.columns = pd.MultiIndex.from_product([[symbol], ['Close']])
            # For indices, yfinance returns simple dataframe, flatten it
            if len(result.columns.levels) > 1:
                result = result.droplevel(0, axis=1)
            return result.tail(HISTORICAL_DAYS)
    
    # Fallback to direct yfinance
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    
    # Ensure we have at least 504 days
    if len(df) < HISTORICAL_DAYS:
        print(f"Warning: Only {len(df)} days available for {symbol}, need {HISTORICAL_DAYS}", file=sys.stderr)
    
    # Keep only the most recent 504 days (or whatever we have)
    df = df.tail(HISTORICAL_DAYS)
    
    return df


def calculate_ma_spreads_for_index(
    symbol: str,
    name: str,
    description: str,
    market_segment: str,
    df: pd.DataFrame
) -> dict:
    """
    Calculate all MA spread metrics for a single index.
    
    Args:
        symbol: Index symbol
        name: Index name
        description: Index description
        market_segment: Market segment
        df: DataFrame with price data
    
    Returns:
        Dictionary with snapshot and historical data
    """
    prices = df['Close']
    
    # Calculate all MAs
    mas = calculate_all_mas(prices, MA_PERIODS)
    
    # Calculate metrics for each MA pair
    all_spread_metrics = {}
    for short_period, long_period, pair_name in MA_PAIRS:
        ma_short = mas[f'ma_{short_period}']
        ma_long = mas[f'ma_{long_period}']
        
        spread_df = calculate_all_ma_spread_metrics(
            ma_short,
            ma_long,
            short_period,
            long_period,
            ZSCORE_LOOKBACK
        )
        all_spread_metrics[pair_name] = {
            'short_period': short_period,
            'long_period': long_period,
            'metrics': spread_df
        }
    
    # Get current (latest) values for snapshot
    latest_date = prices.index[-1]
    latest_price = prices.iloc[-1]
    
    snapshot = {
        'symbol': symbol,
        'name': name,
        'description': description,
        'market_segment': market_segment,
        'date': format_date(latest_date),
        'current_price': safe_float(latest_price),
        'moving_averages': {},
        'ma_pairs': {}
    }
    
    # Add MA values to snapshot
    for period in MA_PERIODS:
        ma_value = mas[f'ma_{period}'].iloc[-1]
        snapshot['moving_averages'][f'ma_{period}'] = safe_float(ma_value)
    
    # Add spread metrics for each MA pair
    for pair_name, pair_data in all_spread_metrics.items():
        short_period = pair_data['short_period']
        long_period = pair_data['long_period']
        metrics = pair_data['metrics']
        
        latest_metrics = {
            'ma_short': short_period,
            'ma_long': long_period,
            'spread': safe_float(metrics['spread'].iloc[-1]),
            'spread_percent': safe_float(metrics['spread_percent'].iloc[-1]),
            'zscore': safe_float(metrics['zscore'].iloc[-1])
        }
        
        # Add signal interpretation
        zscore_val = metrics['zscore'].iloc[-1]
        latest_metrics['signal'] = determine_signal(zscore_val)
        
        # Add crossover status
        spread_val = metrics['spread'].iloc[-1]
        if pd.notna(spread_val):
            if spread_val > 0:
                latest_metrics['alignment'] = 'bullish'
                latest_metrics['alignment_note'] = f'{short_period}-day MA is above {long_period}-day MA'
            else:
                latest_metrics['alignment'] = 'bearish'
                latest_metrics['alignment_note'] = f'{short_period}-day MA is below {long_period}-day MA'
        else:
            latest_metrics['alignment'] = 'insufficient_data'
            latest_metrics['alignment_note'] = 'Not enough data for calculation'
        
        snapshot['ma_pairs'][pair_name] = latest_metrics
    
    # Build historical data
    historical = []
    for i in range(len(prices)):
        date = prices.index[i]
        price = prices.iloc[i]
        
        record = {
            'date': format_date(date),
            'price': safe_float(price),
            'moving_averages': {},
            'ma_pairs': {}
        }
        
        # Add MA values
        for period in MA_PERIODS:
            ma_val = mas[f'ma_{period}'].iloc[i]
            record['moving_averages'][f'ma_{period}'] = safe_float(ma_val)
        
        # Add spread metrics for each pair
        for pair_name, pair_data in all_spread_metrics.items():
            short_period = pair_data['short_period']
            long_period = pair_data['long_period']
            metrics = pair_data['metrics']
            
            record['ma_pairs'][pair_name] = {
                'spread': safe_float(metrics['spread'].iloc[i]),
                'spread_percent': safe_float(metrics['spread_percent'].iloc[i]),
                'zscore': safe_float(metrics['zscore'].iloc[i])
            }
        
        historical.append(record)
    
    # Data quality info
    data_quality = get_data_quality_status(df, HISTORICAL_DAYS)
    
    return {
        'snapshot': snapshot,
        'historical': historical,
        'data_quality': data_quality
    }


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Fetch MA spread mean reversion data')
    parser.add_argument('--cache-dir', type=str, help='Cache directory for parquet files')
    args = parser.parse_args()
    
    print("=" * 80, file=sys.stderr)
    print("MOVING AVERAGE SPREAD MEAN REVERSION COLLECTOR", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Tracking {len(INDICES)} indices", file=sys.stderr)
    print(f"MA periods: {MA_PERIODS}", file=sys.stderr)
    print(f"MA pairs: {len(MA_PAIRS)}", file=sys.stderr)
    for short, long, name in MA_PAIRS:
        print(f"  - {short}-day vs {long}-day ({name})", file=sys.stderr)
    print(f"Historical days: {HISTORICAL_DAYS}", file=sys.stderr)
    print(f"Z-score lookback: {ZSCORE_LOOKBACK}", file=sys.stderr)
    if args.cache_dir:
        print(f"Using cache: {args.cache_dir}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    
    # Prepare output structures
    snapshot_data = {
        '_README': {
            'title': 'Moving Average Spreads - Mean Reversion Snapshot',
            'description': 'Current spread between moving average pairs for major US indices',
            'purpose': 'Identify extreme MA spreads that may signal mean reversion opportunities',
            'update_frequency': 'Every 15 minutes during market hours',
            'indices_tracked': [idx['symbol'] for idx in INDICES],
            'ma_pairs_analyzed': {
                'short_term_vs_intermediate': '20-day vs 50-day MA (swing trading timeframe)',
                'short_term_vs_long_term': '20-day vs 200-day MA (trend identification)',
                'intermediate_vs_long_term': '50-day vs 200-day MA (major trend changes)'
            },
            'metrics_explained': {
                'spread': {
                    'description': 'Point difference between two moving averages',
                    'formula': 'ma_short - ma_long',
                    'interpretation': {
                        'positive': 'Short MA above long MA (bullish alignment)',
                        'negative': 'Short MA below long MA (bearish alignment)',
                        'large_magnitude': 'Wide spread suggests potential snapback to mean'
                    }
                },
                'spread_percent': {
                    'description': 'Percentage spread between two MAs',
                    'formula': '(ma_short - ma_long) / ma_long * 100',
                    'interpretation': 'Normalizes spread for comparison across different price levels',
                    'usage': 'Compare signals across different instruments'
                },
                'zscore': {
                    'description': 'Statistical z-score of MA spread',
                    'formula': '(current_spread - mean_spread) / std_dev(spread)',
                    'lookback_period': f'{ZSCORE_LOOKBACK} days',
                    'interpretation': {
                        '>2': 'Extremely wide spread - Strong mean reversion signal (spread likely to narrow)',
                        '1 to 2': 'Moderately wide spread',
                        '-1 to 1': 'Normal spread range',
                        '-2 to -1': 'Moderately narrow spread',
                        '<-2': 'Extremely narrow/negative spread - Potential breakout or trend reversal'
                    },
                    'usage': 'Most common institutional method for MA spread mean reversion'
                }
            },
            'signal_types': {
                'extremely_overbought': 'Z-score > 2 (spread unusually wide, expect narrowing)',
                'moderately_overbought': 'Z-score 1 to 2 (spread above average)',
                'normal_range': 'Z-score -1 to 1 (spread in normal range)',
                'moderately_oversold': 'Z-score -2 to -1 (spread below average)',
                'extremely_oversold': 'Z-score < -2 (spread unusually narrow, potential expansion)',
                'insufficient_data': 'Not enough data for calculation'
            },
            'alignment_types': {
                'bullish': 'Shorter MA above longer MA (uptrend)',
                'bearish': 'Shorter MA below longer MA (downtrend)'
            },
            'trading_applications': {
                'golden_cross': '50-day crosses above 200-day (bullish signal)',
                'death_cross': '50-day crosses below 200-day (bearish signal)',
                'extreme_spread_mean_reversion': 'Z-score > 2 or < -2 suggests spread will revert to mean',
                'trend_following': 'Trade in direction of MA alignment (bullish/bearish)',
                'swing_trading': 'Use 20-day vs 50-day for short-term entries/exits'
            },
            'professional_usage': {
                'description': 'Institutional traders focus on MA spread z-scores',
                'strategy': 'When spread z-score is extreme, expect snapback to mean',
                'timeframes': {
                    '20_vs_50': 'Swing trading (days to weeks)',
                    '20_vs_200': 'Trend validation (weeks to months)',
                    '50_vs_200': 'Major trend changes (months to years)'
                }
            }
        },
        'metadata': create_metadata(
            indices_count=len(INDICES),
            description='Moving average spread metrics for mean reversion analysis'
        ),
        'indices': {}
    }
    
    historical_data = {
        '_README': {
            'title': 'Moving Average Spreads - Historical Data',
            'description': f'{HISTORICAL_DAYS}-day historical MA spread metrics',
            'purpose': 'Analyze historical MA spread patterns and identify mean reversion opportunities',
            'trading_days': HISTORICAL_DAYS,
            'usage': {
                'backtesting': 'Test MA spread mean reversion strategies',
                'crossover_detection': 'Identify golden/death cross signals in historical data',
                'spread_analysis': 'Study typical spread ranges and extreme levels',
                'strategy_optimization': 'Find optimal z-score thresholds for spread trading'
            }
        },
        'metadata': create_metadata(
            indices_count=len(INDICES),
            description=f'{HISTORICAL_DAYS}-day history of MA spread metrics'
        ),
        'settings': {
            'ma_periods': MA_PERIODS,
            'ma_pairs': [{'short': short, 'long': long, 'name': name} for short, long, name in MA_PAIRS],
            'historical_days': HISTORICAL_DAYS,
            'zscore_lookback': ZSCORE_LOOKBACK
        },
        'indices': {}
    }
    
    # Process each index
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        name = idx_config['name']
        description = idx_config['description']
        market_segment = idx_config['market_segment']
        
        print(f"\nProcessing {symbol} ({name})...", file=sys.stderr)
        
        try:
            # Fetch data
            df = fetch_index_data(symbol, period="2y", cache_dir=args.cache_dir)
            print(f"  Retrieved {len(df)} days of data", file=sys.stderr)
            
            # Calculate metrics
            results = calculate_ma_spreads_for_index(
                symbol, name, description, market_segment, df
            )
            
            # Add to output structures
            snapshot_data['indices'][symbol] = results['snapshot']
            historical_data['indices'][symbol] = {
                'name': name,
                'symbol': symbol,
                'description': description,
                'market_segment': market_segment,
                'data': results['historical'],
                'data_quality': results['data_quality']
            }
            
            # Print latest values
            latest = results['snapshot']
            print(f"  Current price: ${latest['current_price']:.2f}", file=sys.stderr)
            print(f"  Moving averages:", file=sys.stderr)
            for period in MA_PERIODS:
                ma_val = latest['moving_averages'][f'ma_{period}']
                print(f"    {period}-day: ${ma_val:.2f}", file=sys.stderr)
            
            print(f"  MA Spreads:", file=sys.stderr)
            for pair_name, metrics in latest['ma_pairs'].items():
                print(f"    {metrics['ma_short']}-day vs {metrics['ma_long']}-day:", file=sys.stderr)
                print(f"      Spread: {metrics['spread']:.2f} points", file=sys.stderr)
                print(f"      Spread %: {metrics['spread_percent']:.2f}%", file=sys.stderr)
                print(f"      Z-score: {metrics['zscore']:.2f}", file=sys.stderr)
                print(f"      Signal: {metrics['signal']}", file=sys.stderr)
                print(f"      Alignment: {metrics['alignment']} - {metrics['alignment_note']}", file=sys.stderr)
            
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            continue
    
    # Save output files
    output_dir = SCRIPT_DIR / config['settings']['output_dir']
    snapshot_file = output_dir / config['output_files']['ma_spreads']['snapshot']
    historical_file = output_dir / config['output_files']['ma_spreads']['historical']
    
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
