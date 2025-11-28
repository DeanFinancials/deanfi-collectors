"""
Fetch Emerging Markets Indices Data
6 emerging market indices from Latin America and Asia
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

EM_CONFIG = config['emerging_markets_indices']
INDICES = EM_CONFIG['indices']
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
    print("Fetching Emerging Markets Indices snapshot data...")
    
    snapshot_data = {
        "_README": {
            "title": "Emerging Market Indices - Daily Snapshot",
            "description": "Key emerging market equity indices from Latin America, Asia, and other regions",
            "purpose": "Track emerging market performance and identify EM vs DM divergence",
            "markets_included": {idx['symbol']: f"{idx['country']} - {idx['description']}" for idx in INDICES},
            "interpretation": {
                "em_strength": "EM outperforming DM = risk-on, commodity strength",
                "em_weakness": "EM underperforming DM = risk-off, dollar strength",
                "commodity_link": "Brazil, Mexico correlate with commodity prices"
            },
            "pivot_points": {
                "description": "Support and resistance levels for emerging market indices",
                "calculation": "Based on previous trading day's High, Low, and Close prices",
                "application": "Use R1-R3 as overhead resistance, S1-S3 as downside support zones"
            }
        },
        "metadata": create_index_metadata("EM", "Emerging Markets", len(INDICES), len(INDICES)),
        "indices": {},
        "em_summary": {}
    }
    
    em_returns = []
    
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        print(f"  Fetching {symbol} ({idx_config['country']})...")
        
        try:
            # Fetch ticker info for accurate daily change (avoids holiday gap issues)
            ticker = yf.Ticker(symbol)
            ticker_info = ticker.info
            
            df = fetch_index_data(symbol, cache_dir=args.cache_dir)
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
            
            snapshot_data['indices'][symbol] = {
                "name": idx_config['name'],
                "symbol": symbol,
                "country": idx_config['country'],
                "currency": idx_config['currency'],
                "region": idx_config['region'],
                **snapshot,
                **week_52_metrics,
                **returns,
            "pivot_points": pivot_points
            }
            
            if snapshot.get('daily_change_percent'):
                em_returns.append(snapshot['daily_change_percent'])
        except Exception as e:
            print(f"    ❌ Error: {e}")
    
    avg_em_return = sum(em_returns) / len(em_returns) if em_returns else 0
    snapshot_data['em_summary'] = {
        "average_return_1d": safe_round(avg_em_return, 2),
        "em_sentiment": "risk-on" if avg_em_return > 0 else "risk-off"
    }
    
    output_path = os.path.join(SCRIPT_DIR, EM_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved to {output_path}")
    return snapshot_data

def create_historical_json():
    print(f"\nFetching Emerging Markets {HISTORICAL_DAYS}-day historical data...")
    
    historical_data = {
        "_README": {"title": f"Emerging Markets - {HISTORICAL_DAYS}-Day Historical", "trading_days": HISTORICAL_DAYS},
        "metadata": {"generated_at": format_timestamp(), "trading_days": HISTORICAL_DAYS, "indices_count": len(INDICES)},
        "indices": {}
    }
    
    for idx_config in INDICES:
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
    
    output_path = os.path.join(SCRIPT_DIR, EM_CONFIG['output_files']['historical'])
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
    print("EMERGING MARKETS INDICES FETCH")
    print("=" * 80)
    create_snapshot_json()
    create_historical_json()
    print("\n✅ COMPLETE")

if __name__ == "__main__":
    args = parse_args()
    main()
