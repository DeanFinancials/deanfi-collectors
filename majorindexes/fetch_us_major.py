"""
Fetch US Major Market Indices Data

Retrieves daily snapshot and 252-day historical data for 6 core US indices:
- S&P 500 (^GSPC)
- Dow Jones Industrial Average (^DJI)
- Nasdaq Composite (^IXIC)
- Nasdaq-100 (^NDX)
- Russell 2000 (^RUT)
- CBOE Volatility Index (^VIX)

Outputs:
- us_major_indices.json (daily snapshot)
- us_major_indices_historical.json (252-day history with technical indicators)
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
    calculate_all_technical_indicators,
    calculate_returns,
    calculate_52_week_metrics,
    calculate_statistics,
    calculate_pivot_points,
    dataframe_to_daily_records,
    get_current_snapshot_from_info,
    create_index_metadata,
    save_json,
    determine_market_sentiment,
    format_timestamp,
    format_date
)

# Get script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load configuration
with open(os.path.join(SCRIPT_DIR, 'config.yml'), 'r') as f:
    config = yaml.safe_load(f)

US_MAJOR_CONFIG = config['us_major_indices']
INDICES = US_MAJOR_CONFIG['indices']
HISTORICAL_DAYS = config['settings']['historical_days']


def fetch_index_data(symbol: str, period: str = "1y", cache_dir: str = None) -> pd.DataFrame:
    """
    Fetch historical data for an index with optional caching.
    
    Args:
        symbol: Index symbol
        period: Data period (default: "1y" for ~252 trading days)
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
            cache_name=f"majorindexes_us_major"
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
    
    # Ensure we have at least 252 days, fetch more if needed
    if len(df) < HISTORICAL_DAYS:
        df = ticker.history(period="2y")
    
    # Keep only the most recent 252 days (or whatever we have)
    df = df.tail(HISTORICAL_DAYS)
    
    return df


def create_snapshot_json():
    """
    Create daily snapshot JSON with current market data.
    """
    print("Fetching US Major Indices snapshot data...")
    
    snapshot_data = {
        "_README": {
            "title": "US Major Market Indices - Daily Snapshot",
            "description": "Core US equity indices representing the broad market, large-cap, mid-cap, and small-cap segments",
            "purpose": "Track overall US market performance across different market capitalizations",
            "update_frequency": "Daily after market close (4:00 PM ET)",
            "data_source": "Yahoo Finance (yfinance)",
            "last_updated": format_timestamp(),
            "trading_days": f"{HISTORICAL_DAYS} trading days per year",
            "indices_included": {idx['symbol']: f"{idx['name']} - {idx['description']}" for idx in INDICES},
            "metrics_explained": {
                "current_price": "Latest closing price",
                "daily_change": "Point change from previous close",
                "daily_change_percent": "Percentage change from previous close",
                "volume": "Total shares/contracts traded",
                "day_high": "Highest intraday price",
                "day_low": "Lowest intraday price",
                "52_week_high": f"Highest price in past {HISTORICAL_DAYS} trading days",
                "52_week_low": f"Lowest price in past {HISTORICAL_DAYS} trading days",
                "distance_from_52w_high": "Percentage below 52-week high (negative = at high)",
                "year_to_date_return": "Return from Jan 1 to current date",
                "1_month_return": "Rolling 21-day return",
                "3_month_return": "Rolling 63-day return",
                "6_month_return": "Rolling 126-day return",
                "1_year_return": "Rolling 252-day return",
                "pivot_points": "Support/Resistance levels calculated from previous day's High, Low, Close using formula: PP=(H+L+C)/3, R1=(2×PP)-L, S1=(2×PP)-H"
            },
            "pivot_points_usage": {
                "description": "Classic pivot points for intraday support and resistance",
                "calculation": "Based on previous trading day's High, Low, and Close",
                "resistance_levels": "R1, R2, R3 - Price levels where selling pressure may emerge",
                "support_levels": "S1, S2, S3 - Price levels where buying interest may appear",
                "trading_application": "Price above PP = bullish bias, below PP = bearish bias"
            },
            "interpretation": {
                "market_health": "If S&P 500, Dow, and Nasdaq all positive = broad market strength",
                "small_cap_signal": "Russell 2000 outperforming = risk-on sentiment",
                "volatility_signal": "VIX >20 = elevated fear, VIX <15 = complacency",
                "breadth_signal": "All 6 indices green = strong breadth, mixed = rotation"
            }
        },
        "metadata": create_index_metadata(
            symbol="US_MAJOR",
            name="US Major Indices",
            data_count=6,
            indices_total=len(INDICES)
        ),
        "indices": {},
        "market_summary": {}
    }
    
    indices_up = 0
    daily_returns = []
    
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        print(f"  Fetching {symbol}...")
        
        try:
            # Fetch ticker info for accurate daily change (avoids holiday gap issues)
            ticker = yf.Ticker(symbol)
            ticker_info = ticker.info
            
            # Fetch data
            df = fetch_index_data(symbol, period="1y")
            
            if len(df) < 2:
                print(f"    ⚠️  Insufficient data for {symbol}")
                continue
            
            # Current snapshot using ticker.info for accurate daily change
            snapshot = get_current_snapshot_from_info(ticker_info, df)
            
            # Returns
            returns = calculate_returns(df['Close'])
            
            # 52-week metrics
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
            
            # Combine all data
            index_data = {
                "name": idx_config['name'],
                "symbol": symbol,
                "description": idx_config['description'],
                "market_cap_segment": idx_config.get('market_cap_segment'),
                "constituent_count": idx_config.get('constituent_count'),
                **snapshot,
                **week_52_metrics,
                **returns,
                "pivot_points": pivot_points
            }
            
            # Add special notes for VIX
            if symbol == "^VIX":
                index_data["special_notes"] = idx_config.get('special_notes')
            
            snapshot_data['indices'][symbol] = index_data
            
            # Track for summary
            if snapshot.get('daily_change_percent') and snapshot['daily_change_percent'] > 0:
                indices_up += 1
            if snapshot.get('daily_change_percent') is not None:
                daily_returns.append(snapshot['daily_change_percent'])
            
        except Exception as e:
            print(f"    ❌ Error fetching {symbol}: {e}")
            continue
    
    # Market summary
    total_indices = len(snapshot_data['indices'])
    indices_down = total_indices - indices_up
    avg_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    median_return = sorted(daily_returns)[len(daily_returns)//2] if daily_returns else 0
    
    snapshot_data['market_summary'] = {
        "indices_up": indices_up,
        "indices_down": indices_down,
        "average_daily_return": round(avg_return, 2),
        "median_daily_return": round(median_return, 2),
        "market_sentiment": determine_market_sentiment(indices_up, total_indices),
        "breadth_score": round((indices_up / total_indices) * 100, 1) if total_indices > 0 else 0
    }
    
    # Save
    output_path = os.path.join(SCRIPT_DIR, US_MAJOR_CONFIG['output_files']['snapshot'])
    save_json(snapshot_data, output_path)
    print(f"✅ Saved snapshot to {output_path}")
    
    return snapshot_data


def create_historical_json():
    """
    Create 252-day historical JSON with technical indicators.
    """
    print(f"\nFetching US Major Indices {HISTORICAL_DAYS}-day historical data...")
    
    historical_data = {
        "_README": {
            "title": f"US Major Market Indices - {HISTORICAL_DAYS}-Day Historical Data",
            "description": f"Daily historical prices for core US indices covering 1 trading year",
            "purpose": "Enable trend analysis, technical indicators, correlation studies, and performance comparisons",
            "trading_days": HISTORICAL_DAYS,
            "date_range": f"{(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')} to {format_date()}",
            "usage": {
                "charting": "Plot daily close prices to visualize trends",
                "technical_analysis": "Calculate moving averages, RSI, MACD from OHLC data",
                "correlation": "Compare index movements to identify divergences",
                "volatility": "Calculate standard deviation or ATR from daily ranges"
            },
            "technical_indicators_included": {
                "moving_averages": "SMA 20, 50, 200 periods",
                "rsi_14": "14-period Relative Strength Index",
                "macd": "MACD (12, 26, 9) - Moving Average Convergence Divergence",
                "bollinger_bands": "20-period Bollinger Bands (2 standard deviations)"
            },
            "statistics_included": {
                "period_return": f"Total return over {HISTORICAL_DAYS} days",
                "volatility": "Annualized volatility (252 trading days)",
                "max_drawdown": "Largest peak-to-trough decline",
                "sharpe_ratio": "Risk-adjusted return (assuming 4% risk-free rate)",
                "win_rate": "Percentage of days with positive returns"
            }
        },
        "metadata": {
            "generated_at": format_timestamp(),
            "start_date": (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
            "end_date": format_date(),
            "trading_days": HISTORICAL_DAYS,
            "indices_count": len(INDICES),
            "data_source": "Yahoo Finance (yfinance)"
        },
        "indices": {}
    }
    
    for idx_config in INDICES:
        symbol = idx_config['symbol']
        print(f"  Processing {symbol}...")
        
        try:
            # Fetch data
            df = fetch_index_data(symbol, period="1y")
            
            if len(df) < 10:
                print(f"    ⚠️  Insufficient data for {symbol}")
                continue
            
            # Convert to daily records
            daily_data = dataframe_to_daily_records(df)
            
            # Calculate technical indicators
            tech_indicators = calculate_all_technical_indicators(df['Close'])
            
            # Calculate statistics
            stats = calculate_statistics(df['Close'])
            
            # Add average volume if available
            if 'Volume' in df.columns:
                avg_volume = df['Volume'].mean()
                stats['average_daily_volume'] = int(avg_volume) if not pd.isna(avg_volume) else None
            
            # Compile index data
            index_data = {
                "name": idx_config['name'],
                "symbol": symbol,
                "description": idx_config['description'],
                "data": daily_data,
                "technical_indicators": tech_indicators,
                "statistics": stats
            }
            
            historical_data['indices'][symbol] = index_data
            print(f"    ✓ {len(daily_data)} days processed")
            
        except Exception as e:
            print(f"    ❌ Error processing {symbol}: {e}")
            continue
    
    # Save
    output_path = os.path.join(SCRIPT_DIR, US_MAJOR_CONFIG['output_files']['historical'])
    save_json(historical_data, output_path)
    print(f"✅ Saved historical data to {output_path}")
    
    return historical_data



def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch market data with optional caching')
    parser.add_argument('--cache-dir', type=str, default=None, help='Cache directory for parquet files')
    return parser.parse_args()

def main():
    """
    Main execution function.
    """
    print("=" * 80)
    print("US MAJOR INDICES DATA FETCH")
    print("=" * 80)
    print(f"Indices: {len(INDICES)}")
    print(f"Historical Days: {HISTORICAL_DAYS}")
    print(f"Data Source: Yahoo Finance")
    print("=" * 80)
    
    # Create snapshot
    snapshot_data = create_snapshot_json()
    
    # Create historical
    historical_data = create_historical_json()
    
    print("\n" + "=" * 80)
    print("✅ US MAJOR INDICES FETCH COMPLETE")
    print("=" * 80)
    print(f"Snapshot: {len(snapshot_data['indices'])} indices")
    print(f"Historical: {len(historical_data['indices'])} indices")
    print("=" * 80)


if __name__ == "__main__":
    args = parse_args()
    main()
