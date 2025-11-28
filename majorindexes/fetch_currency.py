"""Fetch Currency Index (US Dollar)"""
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

CURRENCY_CONFIG = config['currency_indices']
INDICES = CURRENCY_CONFIG['indices']
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
    print("Fetching Currency Index...")
    snapshot_data = {
        "_README": {
            "title": "Currency Index - Daily Snapshot",
            "description": "US Dollar Index (DXY) strength",
            "interpretation": {
                "dxy_rising": "Dollar strengthening, EM/commodity headwind",
                "dxy_falling": "Dollar weakening, EM/commodity tailwind",
                "threshold": ">100 = strong dollar, <100 = weak dollar"
            },
            "pivot_points": {
                "description": "Support and resistance levels for US Dollar Index (DXY)",
                "calculation": "Pivot Point from previous day's High, Low, Close",
                "importance": "Key technical levels for dollar strength/weakness that impact global markets"
            }
        },
        "metadata": create_index_metadata("CURRENCY", "Currency", len(INDICES), len(INDICES)),
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
                "interpretation": idx['interpretation'],
                "basket_currencies": idx.get('basket_currencies'),
                **get_current_snapshot_from_info(ticker_info, df),
                **calculate_52_week_metrics(df['Close']),
                **calculate_returns(df['Close']),
                "pivot_points": pivot_points
            }
        except Exception as e:
            print(f"    ❌ {e}")
    
    output_path = os.path.join(SCRIPT_DIR, CURRENCY_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching Currency {HISTORICAL_DAYS}-day historical...")
    historical_data = {
        "_README": {"title": f"Currency Index - {HISTORICAL_DAYS}-Day Historical"},
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
    
    output_path = os.path.join(SCRIPT_DIR, CURRENCY_CONFIG['output_files']['historical'])
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
    print("CURRENCY INDEX FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
