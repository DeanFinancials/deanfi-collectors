"""
Fetch US Growth/Value Indices Data

Retrieves daily snapshot and 252-day historical data for 5 Russell growth/value indices:
- Russell 1000 Growth (^RLG)
- Russell 1000 Value (^RLV)
- Russell 2000 Growth (^RUO)
- Russell 2000 Value (^RUJ)
- Russell 3000 (^RUA)

Outputs:
- us_growth_value_indices.json (daily snapshot with style analysis)
- us_growth_value_indices_historical.json (252-day history)
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
    format_date,
    safe_round
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

GROWTH_VALUE_CONFIG = config['us_growth_value_indices']
INDICES = GROWTH_VALUE_CONFIG['indices']
HISTORICAL_DAYS = config['settings']['historical_days']


def fetch_index_data(symbol: str, period: str = "1y", cache_dir: str = None) -> pd.DataFrame:
    """Fetch historical data for an index with optional caching."""
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        fetcher = CachedDataFetcher(cache_dir=str(cache_dir_path))
        df = fetcher.fetch_prices([symbol], period=period, cache_name="majorindexes_growth_value")
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


def analyze_style_performance(indices_data: dict) -> dict:
    """
    Analyze growth vs value and large vs small cap performance.
    """
    analysis = {
        "growth_vs_value": {},
        "cap_size_preference": {},
        "market_regime": "unknown"
    }
    
    # Get performance data
    rlg = indices_data.get('^RLG', {}).get('daily_change_percent', 0) or 0
    rlv = indices_data.get('^RLV', {}).get('daily_change_percent', 0) or 0
    ruo = indices_data.get('^RUO', {}).get('daily_change_percent', 0) or 0
    ruj = indices_data.get('^RUJ', {}).get('daily_change_percent', 0) or 0
    
    # Growth vs Value analysis
    large_cap_leader = "growth" if rlg > rlv else "value"
    large_cap_spread = abs(rlg - rlv)
    
    small_cap_leader = "growth" if ruo > ruj else "value"
    small_cap_spread = abs(ruo - ruj)
    
    # Overall style
    growth_score = (1 if rlg > rlv else 0) + (1 if ruo > ruj else 0)
    overall_style = "growth" if growth_score >= 1 else "value"
    
    analysis['growth_vs_value'] = {
        "large_cap_leader": large_cap_leader,
        "large_cap_spread_percent": safe_round(large_cap_spread, 2),
        "small_cap_leader": small_cap_leader,
        "small_cap_spread_percent": safe_round(small_cap_spread, 2),
        "overall_style_leader": overall_style
    }
    
    # Cap size preference
    growth_leader = "large" if rlg > ruo else "small"
    value_leader = "large" if rlv > ruj else "small"
    
    cap_score = (1 if rlg > ruo else 0) + (1 if rlv > ruj else 0)
    overall_cap = "large-cap" if cap_score >= 1 else "small-cap"
    
    analysis['cap_size_preference'] = {
        "growth_leader": growth_leader,
        "value_leader": value_leader,
        "overall_cap_preference": overall_cap
    }
    
    # Market regime
    if overall_style == "growth" and overall_cap == "large-cap":
        regime = "risk-on, growth-led large-cap"
    elif overall_style == "growth" and overall_cap == "small-cap":
        regime = "aggressive risk-on, small-cap growth"
    elif overall_style == "value" and overall_cap == "large-cap":
        regime = "defensive, quality large-cap value"
    else:
        regime = "risk-on, small-cap value rotation"
    
    analysis['market_regime'] = regime
    
    return analysis


def create_snapshot_json():
    """Create daily snapshot JSON."""
    print("Fetching US Growth/Value Indices snapshot data...")
    
    snapshot_data = {
        "_README": {
            "title": "US Growth vs Value Indices - Daily Snapshot",
            "description": "Russell growth and value indices across large-cap and small-cap segments",
            "purpose": "Track growth vs value performance to identify market style rotation",
            "style_definitions": GROWTH_VALUE_CONFIG['style_definitions'],
            "indices_included": {idx['symbol']: f"{idx['name']} - {idx['description']}" for idx in INDICES},
            "interpretation": {
                "growth_outperforming": "RLG > RLV and RUO > RUJ = Growth stocks leading",
                "value_outperforming": "RLV > RLG and RUJ > RUO = Value stocks leading",
                "large_cap_leading": "RLG > RUO and RLV > RUJ = Large-caps preferred",
                "small_cap_leading": "RUO > RLG and RUJ > RLV = Small-caps preferred",
                "rotation_signal": "Style leadership changes indicate market regime shift"
            },
            "pivot_points": {
                "description": "Support and resistance levels calculated from previous day's price action",
                "formula": "Pivot Point = (High + Low + Close) / 3 from previous trading day",
                "levels": "3 resistance (R1, R2, R3) and 3 support (S1, S2, S3) levels for each index"
            }
        },
        "metadata": create_index_metadata(
            symbol="GROWTH_VALUE",
            name="US Growth/Value Indices",
            data_count=len(INDICES),
            indices_total=len(INDICES)
        ),
        "indices": {},
        "style_analysis": {}
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
                "style": idx_config['style'],
                "market_cap": idx_config['market_cap'],
                **snapshot,
                **week_52_metrics,
                **returns,
            "pivot_points": pivot_points
            }
            
            if 'constituent_count' in idx_config:
                index_data['constituent_count'] = idx_config['constituent_count']
            
            snapshot_data['indices'][symbol] = index_data
            
        except Exception as e:
            print(f"    ❌ Error fetching {symbol}: {e}")
            continue
    
    # Style analysis
    snapshot_data['style_analysis'] = analyze_style_performance(snapshot_data['indices'])
    
    output_path = os.path.join(SCRIPT_DIR, GROWTH_VALUE_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved snapshot to {output_path}")
    
    return snapshot_data


def create_historical_json():
    """Create 252-day historical JSON."""
    print(f"\nFetching US Growth/Value Indices {HISTORICAL_DAYS}-day historical data...")
    
    historical_data = {
        "_README": {
            "title": f"US Growth/Value Indices - {HISTORICAL_DAYS}-Day Historical Data",
            "description": "Historical data for Russell growth and value indices",
            "purpose": "Analyze style rotation trends and performance divergences over time",
            "trading_days": HISTORICAL_DAYS,
            "style_definitions": GROWTH_VALUE_CONFIG['style_definitions']
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
                "style": idx_config['style'],
                "market_cap": idx_config['market_cap'],
                "data": daily_data,
                "technical_indicators": tech_indicators,
                "statistics": stats
            }
            
            historical_data['indices'][symbol] = index_data
            print(f"    ✓ {len(daily_data)} days processed")
            
        except Exception as e:
            print(f"    ❌ Error processing {symbol}: {e}")
            continue
    
    output_path = os.path.join(SCRIPT_DIR, GROWTH_VALUE_CONFIG['output_files']['historical'])
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
    print("US GROWTH/VALUE INDICES DATA FETCH")
    print("=" * 80)
    
    snapshot_data = create_snapshot_json()
    historical_data = create_historical_json()
    
    print("\n" + "=" * 80)
    print("✅ US GROWTH/VALUE INDICES FETCH COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    args = parse_args()
    main()
