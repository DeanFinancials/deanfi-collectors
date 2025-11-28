"""Fetch Dow Jones Family Indices: DJI, DJT, DJU, DJA"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import yaml
import os
from utils import (
    calculate_all_technical_indicators,
    calculate_returns,
    calculate_52_week_metrics,
    calculate_statistics,
    calculate_pivot_points,
    dataframe_to_daily_records,
    get_current_snapshot_from_info,
    create_index_metadata,
    save_json,
    format_timestamp
)
import sys
import argparse
from pathlib import Path

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.cache_manager import CachedDataFetcher

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

DOW_CONFIG = config['dow_family_indices']
INDICES = DOW_CONFIG['indices']
HISTORICAL_DAYS = config['settings']['historical_days']

def fetch_index_data(symbol: str, period: str = "1y", cache_dir: str = None) -> pd.DataFrame:
    """Fetch index data with optional caching."""
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        fetcher = CachedDataFetcher(cache_dir=str(cache_dir_path))
        df = fetcher.fetch_prices([symbol], period=period, cache_name=f"majorindexes_{Path(__file__).stem}")
        if symbol in df.columns:
            result = df[symbol].to_frame()
            if hasattr(result.columns, 'levels') and len(result.columns.levels) > 1:
                result = result.droplevel(0, axis=1)
            return result.tail(HISTORICAL_DAYS)
    
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    return df.tail(HISTORICAL_DAYS) if len(df) >= HISTORICAL_DAYS else ticker.history(period="2y").tail(HISTORICAL_DAYS)

def create_snapshot_json():
    print("Fetching Dow Family Indices...")
    snapshot_data = {
        "_README": {
            "title": "Dow Jones Family Indices - Daily Snapshot",
            "description": "Dow Industrial, Transportation, Utility, and Composite averages",
            "interpretation": {"dow_theory": "DJI and DJT moving together = healthy market trend"},
            "pivot_points": {
                "description": "Classic pivot point levels for each Dow Jones index",
                "formula": "PP=(H+L+C)/3 using previous day's data, then R1=(2×PP)-L, S1=(2×PP)-H",
                "note": "Useful for intraday trading and identifying key support/resistance zones"
            }
        },
        "metadata": create_index_metadata("DOW_FAMILY", "Dow Family", len(INDICES), len(INDICES)),
        "indices": {}
    }
    
    for idx in INDICES:
        symbol = idx['symbol']
        print(f"  {symbol}...")
        try:
            # Fetch ticker info for accurate daily change (avoids holiday gap issues)
            ticker = yf.Ticker(symbol)
            ticker_info = ticker.info
            
            df = fetch_index_data(symbol, cache_dir=args.cache_dir)
            if len(df) < 2:
                continue
            
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
            
            snapshot_data['indices'][symbol] = {
                "name": idx['name'],
                "symbol": symbol,
                "constituent_count": idx['constituent_count'],
                "sector_focus": idx['sector_focus'],
                **get_current_snapshot_from_info(ticker_info, df),
                **calculate_52_week_metrics(df['Close']),
                **calculate_returns(df['Close']),
                "pivot_points": pivot_points
            }
        except Exception as e:
            print(f"    ❌ {e}")
    
    output_path = os.path.join(SCRIPT_DIR, DOW_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved to {output_path}")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching Dow Family {HISTORICAL_DAYS}-day historical...")
    historical_data = {
        "_README": {"title": f"Dow Family - {HISTORICAL_DAYS}-Day Historical"},
        "metadata": {"generated_at": format_timestamp(), "trading_days": HISTORICAL_DAYS},
        "indices": {}
    }
    
    for idx in INDICES:
        symbol = idx['symbol']
        print(f"  {symbol}...")
        try:
            df = fetch_index_data(symbol, cache_dir=args.cache_dir)
            if len(df) < 10:
                continue
            historical_data['indices'][symbol] = {
                "name": idx['name'],
                "symbol": symbol,
                "data": dataframe_to_daily_records(df),
                "technical_indicators": calculate_all_technical_indicators(df['Close']),
                "statistics": calculate_statistics(df['Close'])
            }
            print(f"    ✓ {len(df)} days")
        except Exception as e:
            print(f"    ❌ {e}")
    
    output_path = os.path.join(SCRIPT_DIR, DOW_CONFIG['output_files']['historical'])
    save_json(historical_data, output_path)
    print(f"✅ Saved")
    return historical_data


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    print("=" * 80)
    print("DOW FAMILY INDICES FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
