"""
Fetch US Sector Indices Data

Retrieves daily snapshot and 252-day historical data for 11 GICS sectors:
XLK, XLV, XLF, XLY, XLI, XLP, XLE, XLB, XLC, XLU, XLRE

Outputs:
- us_sector_indices.json (daily snapshot with sector rankings)
- us_sector_indices_historical.json (252-day history)
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
    rank_by_performance,
    format_timestamp,
    format_date,
    safe_round
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

SECTOR_CONFIG = config['us_sector_indices']
SECTORS = SECTOR_CONFIG['sectors']
HISTORICAL_DAYS = config['settings']['historical_days']
BENCHMARK = SECTOR_CONFIG['benchmark']


def fetch_index_data(symbol: str, period: str = "1y", cache_dir: str = None) -> pd.DataFrame:
    """Fetch historical data for an index with optional caching."""
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        fetcher = CachedDataFetcher(cache_dir=str(cache_dir_path))
        df = fetcher.fetch_prices([symbol], period=period, cache_name="majorindexes_sectors")
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


def calculate_sector_summary(indices_data: dict, benchmark_return: float = None) -> dict:
    """Calculate sector rotation metrics and rankings."""
    
    # Rank sectors by daily performance
    rankings_1d = rank_by_performance(indices_data, 'daily_change_percent')
    
    # Rank sectors by 1-month performance
    rankings_1m = rank_by_performance(indices_data, '1_month_percent')
    
    # Top/bottom performers
    top_performers = rankings_1d[:3] if len(rankings_1d) >= 3 else rankings_1d
    bottom_performers = rankings_1d[-3:] if len(rankings_1d) >= 3 else []
    bottom_performers.reverse()  # Show worst first
    
    # Count sectors beating benchmark
    sectors_beating_sp500 = 0
    for symbol, data in indices_data.items():
        if benchmark_return is not None:
            rel_perf = data.get('daily_change_percent', 0)
            if rel_perf and rel_perf > benchmark_return:
                sectors_beating_sp500 += 1
    
    total_sectors = len(indices_data)
    breadth_score = (sectors_beating_sp500 / total_sectors * 100) if total_sectors > 0 else 0
    
    # Determine market leadership
    defensive_sectors = ['XLU', 'XLP', 'XLV']
    cyclical_sectors = ['XLY', 'XLK', 'XLI', 'XLF']
    
    defensive_avg = 0
    cyclical_avg = 0
    defensive_count = 0
    cyclical_count = 0
    
    for symbol, data in indices_data.items():
        ret = data.get('daily_change_percent', 0) or 0
        if symbol in defensive_sectors:
            defensive_avg += ret
            defensive_count += 1
        elif symbol in cyclical_sectors:
            cyclical_avg += ret
            cyclical_count += 1
    
    if defensive_count > 0:
        defensive_avg /= defensive_count
    if cyclical_count > 0:
        cyclical_avg /= cyclical_count
    
    if cyclical_avg > defensive_avg:
        leadership = "cyclical"
        defensive_strength = "weak"
    else:
        leadership = "defensive"
        defensive_strength = "strong"
    
    summary = {
        "top_performers_1d": [
            {"sector": symbol, "return": safe_round(ret, 2)} 
            for symbol, ret in top_performers
        ],
        "bottom_performers_1d": [
            {"sector": symbol, "return": safe_round(ret, 2)} 
            for symbol, ret in bottom_performers
        ],
        "sectors_beating_sp500": sectors_beating_sp500,
        "breadth_score": safe_round(breadth_score, 1),
        "market_leadership": leadership,
        "defensive_strength": defensive_strength
    }
    
    return summary


def create_snapshot_json():
    """Create daily snapshot JSON."""
    print("Fetching US Sector Indices snapshot data...")
    
    snapshot_data = {
        "_README": {
            "title": "US Sector Indices - Daily Snapshot (GICS 11 Sectors)",
            "description": "Performance of 11 GICS sectors via Select Sector SPDR ETFs",
            "purpose": "Identify sector rotation, leadership, and relative strength",
            "sectors_explained": {
                sector['symbol']: f"{sector['sector_name']} - {sector['description']}"
                for sector in SECTORS
            },
            "interpretation": {
                "sector_rotation": "Compare 1-month returns to identify hot sectors",
                "defensive_vs_cyclical": "XLU/XLP outperforming = defensive, XLY/XLK = risk-on",
                "leadership_count": "Count sectors beating S&P 500 for breadth signal",
                "relative_strength": "Sectors at 52-week highs = strongest momentum"
            },
            "pivot_points_usage": {
                "description": "Daily support/resistance levels based on previous day's High, Low, Close",
                "formula": "PP=(H+L+C)/3, R1=(2×PP)-L, R2=PP+(H-L), R3=H+(2×(PP-L)), S1=(2×PP)-H, S2=PP-(H-L), S3=L-(2×(H-L))",
                "application": "Identify potential reversal points and sector strength thresholds"
            },
            "gics_classification": {
                "10": "Energy (XLE)",
                "15": "Materials (XLB)",
                "20": "Industrials (XLI)",
                "25": "Consumer Discretionary (XLY)",
                "30": "Consumer Staples (XLP)",
                "35": "Health Care (XLV)",
                "40": "Financials (XLF)",
                "45": "Technology (XLK)",
                "50": "Communication Services (XLC)",
                "55": "Utilities (XLU)",
                "60": "Real Estate (XLRE)"
            }
        },
        "metadata": create_index_metadata(
            symbol="SECTORS",
            name="US Sector Indices",
            data_count=len(SECTORS),
            indices_total=len(SECTORS)
        ),
        "sectors": {},
        "sector_summary": {}
    }
    
    # Fetch benchmark (S&P 500) for relative performance
    benchmark_return = None
    try:
        sp500_ticker = yf.Ticker(BENCHMARK)
        sp500_info = sp500_ticker.info
        sp500_df = fetch_index_data(BENCHMARK, period="5d")
        if len(sp500_df) >= 2:
            sp500_snapshot = get_current_snapshot_from_info(sp500_info, sp500_df)
            benchmark_return = sp500_snapshot.get('daily_change_percent')
    except Exception as e:
        print(f"  ⚠️  Could not fetch benchmark {BENCHMARK}: {e}")
    
    # Fetch sector data
    for sector in SECTORS:
        symbol = sector['symbol']
        print(f"  Fetching {symbol} ({sector['sector_name']})...")
        
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
            
            # Calculate relative performance to S&P 500
            relative_perf_1d = None
            relative_perf_1m = None
            if benchmark_return is not None:
                sector_return = snapshot.get('daily_change_percent')
                if sector_return is not None:
                    relative_perf_1d = safe_round(sector_return - benchmark_return, 2)
            
            sector_data = {
                "name": sector['name'],
                "symbol": symbol,
                "sector_name": sector['sector_name'],
                "gics_code": sector['gics_code'],
                "description": sector['description'],
                **snapshot,
                **week_52_metrics,
                **returns,
                "relative_to_sp500_1d": relative_perf_1d,
                "pivot_points": pivot_points
            }
            
            snapshot_data['sectors'][symbol] = sector_data
            
        except Exception as e:
            print(f"    ❌ Error fetching {symbol}: {e}")
            continue
    
    # Calculate sector summary
    snapshot_data['sector_summary'] = calculate_sector_summary(
        snapshot_data['sectors'],
        benchmark_return
    )
    
    output_path = os.path.join(SCRIPT_DIR, SECTOR_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved snapshot to {output_path}")
    
    return snapshot_data


def create_historical_json():
    """Create 252-day historical JSON."""
    print(f"\nFetching US Sector Indices {HISTORICAL_DAYS}-day historical data...")
    
    historical_data = {
        "_README": {
            "title": f"US Sector Indices - {HISTORICAL_DAYS}-Day Historical Data",
            "description": "Historical data for 11 GICS sectors",
            "purpose": "Analyze sector rotation trends and relative performance over time",
            "trading_days": HISTORICAL_DAYS
        },
        "metadata": {
            "generated_at": format_timestamp(),
            "start_date": (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
            "end_date": format_date(),
            "trading_days": HISTORICAL_DAYS,
            "sectors_count": len(SECTORS)
        },
        "sectors": {}
    }
    
    for sector in SECTORS:
        symbol = sector['symbol']
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
            
            sector_data = {
                "name": sector['name'],
                "symbol": symbol,
                "sector_name": sector['sector_name'],
                "gics_code": sector['gics_code'],
                "data": daily_data,
                "technical_indicators": tech_indicators,
                "statistics": stats
            }
            
            historical_data['sectors'][symbol] = sector_data
            print(f"    ✓ {len(daily_data)} days processed")
            
        except Exception as e:
            print(f"    ❌ Error processing {symbol}: {e}")
            continue
    
    output_path = os.path.join(SCRIPT_DIR, SECTOR_CONFIG['output_files']['historical'])
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
    print("US SECTOR INDICES DATA FETCH")
    print("=" * 80)
    
    snapshot_data = create_snapshot_json()
    historical_data = create_historical_json()
    
    print("\n" + "=" * 80)
    print("✅ US SECTOR INDICES FETCH COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    args = parse_args()
    main()
