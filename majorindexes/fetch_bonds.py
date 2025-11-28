"""Fetch Bond/Treasury Yield Indices"""
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
    format_timestamp,
    safe_round
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

BOND_CONFIG = config['bond_treasury_indices']
INDICES = BOND_CONFIG['indices']
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

def calculate_yield_curve(indices_data: dict) -> dict:
    """Calculate yield curve steepness and inversion status"""
    try:
        y_3m = indices_data.get('^IRX', {}).get('current_price')
        y_5y = indices_data.get('^FVX', {}).get('current_price')
        y_10y = indices_data.get('^TNX', {}).get('current_price')
        y_30y = indices_data.get('^TYX', {}).get('current_price')
        
        spread_10y_3m = safe_round(y_10y - y_3m, 2) if y_10y and y_3m else None
        spread_10y_2y = None  # Would need 2Y data
        
        curve_status = "normal"
        if spread_10y_3m and spread_10y_3m < 0:
            curve_status = "inverted"
        elif spread_10y_3m and spread_10y_3m < 0.5:
            curve_status = "flat"
        elif spread_10y_3m and spread_10y_3m > 2:
            curve_status = "steep"
        
        return {
            "spread_10y_3m": spread_10y_3m,
            "curve_status": curve_status,
            "yields": {
                "3_month": y_3m,
                "5_year": y_5y,
                "10_year": y_10y,
                "30_year": y_30y
            }
        }
    except:
        return {}

def create_snapshot_json():
    print("Fetching Bond/Treasury Indices...")
    snapshot_data = {
        "_README": {
            "title": "Bond/Treasury Yield Indices - Daily Snapshot",
            "description": "US Treasury yields across different maturities",
            "interpretation": {
                "yield_curve_inversion": "10Y < 3M yield = recession warning",
                "rising_yields": "Bond prices falling, potential equity headwind",
                "falling_yields": "Flight to safety, equity concerns"
            },
            "pivot_points": {
                "description": "Support/resistance for treasury yield levels (note: yields, not prices)",
                "calculation": "Based on previous day's High, Low, Close yield levels",
                "usage": "Track pivot levels to identify key yield thresholds and reversal points"
            }
        },
        "metadata": create_index_metadata("BONDS", "Treasury Yields", len(INDICES), len(INDICES)),
        "indices": {},
        "yield_curve_analysis": {}
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
                "maturity_years": idx.get('maturity_years'),
                "duration": idx['duration'],
                "interpretation": idx['interpretation'],
                **get_current_snapshot_from_info(ticker_info, df),
                **calculate_52_week_metrics(df['Close']),
                **calculate_returns(df['Close']),
                "pivot_points": pivot_points
            }
        except Exception as e:
            print(f"    ❌ {e}")
    
    snapshot_data['yield_curve_analysis'] = calculate_yield_curve(snapshot_data['indices'])
    
    output_path = os.path.join(SCRIPT_DIR, BOND_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching Bonds {HISTORICAL_DAYS}-day historical...")
    historical_data = {
        "_README": {"title": f"Treasury Yields - {HISTORICAL_DAYS}-Day Historical"},
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
    
    output_path = os.path.join(SCRIPT_DIR, BOND_CONFIG['output_files']['historical'])
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
    print("BOND/TREASURY INDICES FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
