"""
Fetch International Major Market Indices Data
11 developed market indices from Europe, Asia, and other regions
"""

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

INTL_CONFIG = config['international_major_indices']
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
    if len(df) < HISTORICAL_DAYS:
        df = ticker.history(period="2y")
    return df.tail(HISTORICAL_DAYS)

def create_snapshot_json():
    print("Fetching International Indices snapshot data...")
    
    all_indices = []
    for region_name, region_indices in INTL_CONFIG['regions'].items():
        all_indices.extend(region_indices)
    
    snapshot_data = {
        "_README": {
            "title": "International Major Market Indices - Daily Snapshot",
            "description": "Major developed market indices from Europe, Asia, and other regions",
            "purpose": "Track global market performance and identify regional divergences",
            "regions_covered": {
                "europe": "UK, Germany, France, Eurozone, Switzerland",
                "asia_pacific": "Japan, Hong Kong, Australia, South Korea",
                "other": "Canada, Israel"
            },
            "time_zone_note": "Prices reflect local market closes, not synchronized globally",
            "interpretation": {
                "global_risk_on": "All regions positive = broad global strength",
                "regional_divergence": "Europe strong, Asia weak = regional issues",
                "leading_indicator": "Asian markets close first, may signal US direction"
            },
            "pivot_points": {
                "description": "Daily pivot levels for international indices based on previous session",
                "note": "Calculated from previous day's High, Low, Close in local market hours",
                "levels": "Pivot Point, R1-R3 resistance, S1-S3 support for each international index"
            }
        },
        "metadata": create_index_metadata("INTERNATIONAL", "International Indices", len(all_indices), len(all_indices)),
        "indices": {},
        "regional_summary": {}
    }
    
    regional_data = {}
    
    for region_name, region_indices in INTL_CONFIG['regions'].items():
        regional_data[region_name] = {'indices_up': 0, 'indices_down': 0, 'returns': []}
        
        for idx_config in region_indices:
            symbol = idx_config['symbol']
            print(f"  Fetching {symbol} ({idx_config['country']})...")
            
            try:
                # Fetch ticker info for accurate daily change (avoids holiday gap issues)
                ticker = yf.Ticker(symbol)
                ticker_info = ticker.info
                
                df = fetch_index_data(symbol, period="1y")
                if len(df) < 2:
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
                    "country": idx_config['country'],
                    "currency": idx_config['currency'],
                    "region": region_name,
                    **snapshot,
                    **week_52_metrics,
                    **returns,
                "pivot_points": pivot_points
                }
                
                snapshot_data['indices'][symbol] = index_data
                
                if snapshot.get('daily_change_percent', 0) > 0:
                    regional_data[region_name]['indices_up'] += 1
                else:
                    regional_data[region_name]['indices_down'] += 1
                if snapshot.get('daily_change_percent'):
                    regional_data[region_name]['returns'].append(snapshot['daily_change_percent'])
                    
            except Exception as e:
                print(f"    ❌ Error: {e}")
    
    # Regional summary
    for region, data in regional_data.items():
        total = data['indices_up'] + data['indices_down']
        avg_return = sum(data['returns']) / len(data['returns']) if data['returns'] else 0
        
        snapshot_data['regional_summary'][region] = {
            "average_return_1d": safe_round(avg_return, 2),
            "indices_count": total,
            "indices_up": data['indices_up'],
            "indices_down": data['indices_down'],
            "regional_sentiment": "positive" if data['indices_up'] > data['indices_down'] else "negative"
        }
    
    output_path = os.path.join(SCRIPT_DIR, INTL_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved snapshot to {output_path}")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching International Indices {HISTORICAL_DAYS}-day historical data...")
    
    all_indices = []
    for region_indices in INTL_CONFIG['regions'].values():
        all_indices.extend(region_indices)
    
    historical_data = {
        "_README": {
            "title": f"International Indices - {HISTORICAL_DAYS}-Day Historical Data",
            "description": "Historical data for developed market indices",
            "trading_days": HISTORICAL_DAYS
        },
        "metadata": {
            "generated_at": format_timestamp(),
            "trading_days": HISTORICAL_DAYS,
            "indices_count": len(all_indices)
        },
        "indices": {}
    }
    
    for idx_config in all_indices:
        symbol = idx_config['symbol']
        print(f"  Processing {symbol}...")
        
        try:
            df = fetch_index_data(symbol, cache_dir=args.cache_dir)
            if len(df) < 10:
                continue
            
            historical_data['indices'][symbol] = {
                "name": idx_config['name'],
                "symbol": symbol,
                "country": idx_config['country'],
                "data": dataframe_to_daily_records(df),
                "technical_indicators": calculate_all_technical_indicators(df['Close']),
                "statistics": calculate_statistics(df['Close'])
            }
            print(f"    ✓ {len(df)} days")
        except Exception as e:
            print(f"    ❌ Error: {e}")
    
    output_path = os.path.join(SCRIPT_DIR, INTL_CONFIG['output_files']['historical'])
    save_json(historical_data, output_path)
    print(f"✅ Saved to {output_path}")
    return historical_data


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    print("=" * 80)
    print("INTERNATIONAL INDICES DATA FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
