"""Fetch Commodity Indices"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import yaml
import os
from utils import *
import sys
import argparse
from pathlib import Path

# Add parent directory to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.cache_manager import CachedDataFetcher

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

COMMODITY_CONFIG = config['commodity_indices']
INDICES = COMMODITY_CONFIG['indices']
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
    print("Fetching Commodity Indices...")
    snapshot_data = {
        "_README": {
            "title": "Commodity Indices - Daily Snapshot",
            "description": "Major commodity futures and ETFs",
            "interpretation": {
                "gold_rising": "Risk-off sentiment, inflation hedge",
                "oil_rising": "Economic growth expectations",
                "correlation": "Commodities often correlate with EM performance"
            },
            "pivot_points": {
                "description": "Daily pivot levels for commodity futures and ETFs",
                "formula": "PP=(Previous High + Low + Close)/3, plus R1-R3 and S1-S3 levels",
                "note": "Particularly useful for oil and gold where technical levels are closely watched"
            }
        },
        "metadata": create_index_metadata("COMMODITIES", "Commodities", len(INDICES), len(INDICES)),
        "indices": {}
    }
    
    for idx in INDICES:
        symbol = idx['symbol']
        print(f"  {symbol}...")
        try:
            # Fetch ticker info for accurate daily change (avoids holiday gap issues)
            ticker = yf.Ticker(symbol)
            ticker_info = ticker.info
            
            # Also fetch historical data for 52-week metrics, returns, and pivot points
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
            
            # Use ticker.info for daily snapshot (more reliable for futures with gaps)
            snapshot_data['indices'][symbol] = {
                "name": idx['name'],
                "symbol": symbol,
                "commodity_type": idx['commodity_type'],
                "unit": idx.get('unit'),
                "is_etf": idx.get('is_etf', False),
                **get_current_snapshot_from_info(ticker_info, df),
                **calculate_52_week_metrics(df['Close']),
                **calculate_returns(df['Close']),
                "pivot_points": pivot_points
            }
        except Exception as e:
            print(f"    ❌ {e}")
    
    output_path = os.path.join(SCRIPT_DIR, COMMODITY_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching Commodities {HISTORICAL_DAYS}-day historical...")
    historical_data = {
        "_README": {"title": f"Commodities - {HISTORICAL_DAYS}-Day Historical"},
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
                "commodity_type": idx['commodity_type'],
                "data": dataframe_to_daily_records(df),
                "technical_indicators": calculate_all_technical_indicators(df['Close']),
                "statistics": calculate_statistics(df['Close'])
            }
            print(f"    ✓ {len(df)} days")
        except Exception as e:
            print(f"    ❌ {e}")
    
    output_path = os.path.join(SCRIPT_DIR, COMMODITY_CONFIG['output_files']['historical'])
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
    print("COMMODITY INDICES FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
