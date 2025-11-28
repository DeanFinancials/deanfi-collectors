"""
Fetch US Equal-Weight Indices Data

Retrieves daily snapshot and 252-day historical data for 4 equal-weight indices:
- S&P 500 Equal Weight Index (^SPXEW)
- Nasdaq-100 Equal Weight Index (^NDXE)
- Invesco S&P 500 Equal Weight ETF (RSP)
- First Trust Nasdaq-100 Equal Weight ETF (QQEW)

Outputs:
- us_equal_weight_indices.json (daily snapshot)
- us_equal_weight_indices_historical.json (252-day history)
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import yaml
import os
import sys
import argparse
from pathlib import Path

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.cache_manager import CachedDataFetcher

from utils import (
    calculate_pivot_points,
    calculate_all_technical_indicators,
    calculate_returns,
    calculate_52_week_metrics,
    calculate_statistics,
    dataframe_to_daily_records,
    get_current_snapshot_from_info,
    create_index_metadata,
    save_json,
    format_timestamp,
    format_date
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

EQUAL_WEIGHT_CONFIG = config['us_equal_weight_indices']
INDICES = EQUAL_WEIGHT_CONFIG['indices']
HISTORICAL_DAYS = config['settings']['historical_days']


def fetch_index_data(symbol: str, period: str = "1y", cache_dir: str = None) -> pd.DataFrame:
    """Fetch historical data for an index with optional caching."""
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        fetcher = CachedDataFetcher(cache_dir=str(cache_dir_path))
        df = fetcher.fetch_prices([symbol], period=period, cache_name="majorindexes_equal_weight")
        if symbol in df.columns:
            result = df[symbol].to_frame()
            if hasattr(result.columns, 'levels') and len(result.columns.levels) > 1:
                result = result.droplevel(0, axis=1)
            return result.tail(HISTORICAL_DAYS)
    
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    if len(df) < HISTORICAL_DAYS:
        df = ticker.history(period="2y")
    return df.tail(HISTORICAL_DAYS)


def create_snapshot_json():
    """Create daily snapshot JSON."""
    print("Fetching US Equal-Weight Indices snapshot data...")
    
    snapshot_data = {
        "_README": {
            "title": "US Equal-Weight Indices - Daily Snapshot",
            "description": "Equal-weighted versions of major indices (each stock has same weight regardless of market cap)",
            "purpose": "Compare equal-weight vs market-cap weighted performance to identify concentration risk",
            "indices_included": {idx['symbol']: f"{idx['name']} - {idx['description']}" for idx in INDICES},
            "equal_weight_explained": {
                "concept": "Each constituent has equal portfolio weight (e.g., 0.2% for S&P 500)",
                "vs_market_cap": "Market-cap weighted indices give more weight to larger companies",
                "benefit": "Reduces concentration risk from mega-cap stocks",
                "signal": "Equal-weight outperforming = broad participation, cap-weight outperforming = large-cap dominance"
            },
            "interpretation": {
                "equal_weight_leading": "RSP > SPY or SPXEW rising = Broad market strength, less concentration",
                "cap_weight_leading": "SPY > RSP or cap-weight outperforming = Large-cap dominance, narrow leadership",
                "divergence_signal": "Performance gap widening indicates increasing market concentration"
            },
            "pivot_points": {
                "description": "Intraday support/resistance levels based on previous day's trading range",
                "calculation": "PP = (Previous High + Low + Close) / 3",
                "usage": "Track R1/R2/R3 for resistance, S1/S2/S3 for support in equal-weight indices"
            }
        },
        "metadata": create_index_metadata(
            symbol="EQUAL_WEIGHT",
            name="US Equal-Weight Indices",
            data_count=len(INDICES),
            indices_total=len(INDICES)
        ),
        "indices": {}
    }
    
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        print(f"  Fetching {symbol}...")
        
        try:
            # Fetch ticker info for accurate daily change (avoids holiday gap issues)
            ticker = yf.Ticker(symbol)
            ticker_info = ticker.info
            
            df = fetch_index_data(symbol, period="1y")
            if len(df) < 2:
                print(f"    ⚠️  Insufficient data for {symbol}")
                continue
            
            snapshot = get_current_snapshot_from_info(ticker_info, df)
            returns = calculate_returns(df['Close'])
            week_52_metrics = calculate_52_week_metrics(df['Close'])

            # Pivot points (previous day's H, L, C)
            if len(df) >= 2:
                prev_day = df.iloc[-2]
                pivot_points = calculate_pivot_points(
                    high=prev_day['High'],
                    low=prev_day['Low'],
                    close=prev_day['Close']
                )
            else:
                pivot_points = {}
            
            index_data = {
                "name": idx_config['name'],
                "symbol": symbol,
                "description": idx_config['description'],
                "parent_index": idx_config.get('parent_index'),
                "is_etf": idx_config.get('is_etf', False),
                **snapshot,
                **week_52_metrics,
                **returns,
            "pivot_points": pivot_points
            }
            
            snapshot_data['indices'][symbol] = index_data
            
        except Exception as e:
            print(f"    ❌ Error fetching {symbol}: {e}")
            continue
    
    output_path = os.path.join(SCRIPT_DIR, EQUAL_WEIGHT_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved snapshot to {output_path}")
    
    return snapshot_data


def create_historical_json():
    """Create 252-day historical JSON."""
    print(f"\nFetching US Equal-Weight Indices {HISTORICAL_DAYS}-day historical data...")
    
    historical_data = {
        "_README": {
            "title": f"US Equal-Weight Indices - {HISTORICAL_DAYS}-Day Historical Data",
            "description": "Historical data for equal-weighted index variants",
            "purpose": "Track concentration risk and breadth trends over time",
            "trading_days": HISTORICAL_DAYS
        },
        "metadata": {
            "generated_at": format_timestamp(),
            "start_date": (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
            "end_date": format_date(),
            "trading_days": HISTORICAL_DAYS,
            "indices_count": len(INDICES)
        },
        "indices": {}
    }
    
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        print(f"  Processing {symbol}...")
        
        try:
            df = fetch_index_data(symbol, period="1y")
            if len(df) < 10:
                print(f"    ⚠️  Insufficient data for {symbol}")
                continue
            
            daily_data = dataframe_to_daily_records(df)
            tech_indicators = calculate_all_technical_indicators(df['Close'])
            stats = calculate_statistics(df['Close'])
            
            if 'Volume' in df.columns:
                stats['average_daily_volume'] = int(df['Volume'].mean()) if not pd.isna(df['Volume'].mean()) else None
            
            index_data = {
                "name": idx_config['name'],
                "symbol": symbol,
                "parent_index": idx_config.get('parent_index'),
                "is_etf": idx_config.get('is_etf', False),
                "data": daily_data,
                "technical_indicators": tech_indicators,
                "statistics": stats
            }
            
            historical_data['indices'][symbol] = index_data
            print(f"    ✓ {len(daily_data)} days processed")
            
        except Exception as e:
            print(f"    ❌ Error processing {symbol}: {e}")
            continue
    
    output_path = os.path.join(SCRIPT_DIR, EQUAL_WEIGHT_CONFIG['output_files']['historical'])
    save_json(historical_data, output_path)
    print(f"✅ Saved historical data to {output_path}")
    
    return historical_data



def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    """Main execution function."""
    print("=" * 80)
    print("US EQUAL-WEIGHT INDICES DATA FETCH")
    print("=" * 80)
    
    snapshot_data = create_snapshot_json()
    historical_data = create_historical_json()
    
    print("\n" + "=" * 80)
    print("✅ US EQUAL-WEIGHT INDICES FETCH COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    args = parse_args()
    main()
