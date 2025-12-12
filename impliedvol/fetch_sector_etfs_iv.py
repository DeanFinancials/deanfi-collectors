"""
Fetch implied volatility data for S&P 500 Sector ETFs.

Fetches ATM option IV data for all 11 sector ETFs:
XLK, XLV, XLF, XLE, XLY, XLP, XLI, XLU, XLB, XLRE, XLC

Outputs:
- sector_etfs_iv_snapshot.json: Current IV snapshot with option details
- sector_etfs_iv_historical.json: 252 days of IV data with moving averages
"""

import json
import yaml
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd

# Use Eastern Time for market data timestamps
ET = ZoneInfo('America/New_York')

from utils import (
    get_option_snapshot,
    classify_iv_level,
    format_iv_percentage,
    serialize_for_json,
    get_iv_historical_reference
)

# Load config
CONFIG_PATH = Path(__file__).parent / 'config.yml'
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

SECTOR_ETFS = config['sector_etfs']
OPTIONS_CRITERIA = config['options_criteria']
OUTPUT_CONFIG = config['output']['sector_etfs']


def fetch_sector_etfs_snapshot():
    """
    Fetch current IV snapshot for all sector ETFs.
    
    Returns:
        Dict with metadata and sector ETF IV data
    """
    print("="*80)
    print("FETCHING SECTOR ETFs IMPLIED VOLATILITY SNAPSHOT")
    print("="*80)
    print(f"Symbols: {', '.join(SECTOR_ETFS.keys())}")
    print(f"Timestamp: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    results = {}
    success_count = 0
    
    for symbol, info in SECTOR_ETFS.items():
        print(f"Fetching {symbol} ({info['sector']})...", end=' ')
        
        snapshot = get_option_snapshot(
            symbol,
            min_dte=OPTIONS_CRITERIA['min_dte'],
            max_dte=OPTIONS_CRITERIA['max_dte'],
            atm_tolerance=OPTIONS_CRITERIA['atm_tolerance']
        )
        
        if snapshot:
            # Add sector metadata
            snapshot['sector'] = info['sector']
            snapshot['name'] = info['name']
            snapshot['description'] = info['description']
            
            # Format IV percentages for display
            snapshot['average_iv_formatted'] = format_iv_percentage(snapshot['average_iv'])
            snapshot['iv_level'] = classify_iv_level(snapshot['average_iv'])
            
            # Add historical reference data
            hist_ref = get_iv_historical_reference(symbol)
            snapshot['historical_reference'] = {
                'historical_avg': hist_ref['historical_avg'],
                'historical_avg_formatted': hist_ref['historical_avg_formatted'],
                'typical_low': hist_ref['typical_range']['low'],
                'typical_high': hist_ref['typical_range']['high'],
                'current_vs_average': None if hist_ref['historical_avg'] is None else 
                    round(snapshot['average_iv'] - hist_ref['historical_avg'], 4),
                'current_vs_average_pct': None if hist_ref['historical_avg'] is None else
                    f"{((snapshot['average_iv'] / hist_ref['historical_avg'] - 1) * 100):.2f}%"
            }
            
            results[symbol] = snapshot
            success_count += 1
            print(f"✅ IV: {snapshot['average_iv_formatted']}")
        else:
            print("❌ Failed")
    
    print()
    print(f"Successfully fetched: {success_count}/{len(SECTOR_ETFS)}")
    
    # Build output
    output = {
        '_README': {
            'description': 'Implied volatility snapshot for S&P 500 sector ETFs',
            'data_source': 'yfinance (Yahoo Finance) - Options data',
            'update_frequency': 'Real-time (run script to update)',
            'last_updated': datetime.now(ET).isoformat(),
            'num_symbols': len(results),
            'symbols': list(results.keys()),
            'options_criteria': {
                'min_days_to_expiration': OPTIONS_CRITERIA['min_dte'],
                'max_days_to_expiration': OPTIONS_CRITERIA['max_dte'],
                'atm_tolerance': f"{OPTIONS_CRITERIA['atm_tolerance']*100}%"
            },
            'fields_explanation': {
                'current_price': 'Current ETF price',
                'expiration_date': 'Option expiration date used',
                'days_to_expiration': 'Days until expiration',
                'average_iv': 'Average of ATM call and put implied volatility',
                'average_iv_formatted': 'IV as percentage (e.g., 25.50%)',
                'iv_level': 'Classification: Low, Normal, Elevated, High, Extreme',
                'atm_call': 'ATM call option details (strike, IV, prices, liquidity)',
                'atm_put': 'ATM put option details (strike, IV, prices, liquidity)',
                'moneyness': 'Strike / Underlying price',
                'pct_from_atm': 'Percentage difference from ATM',
                'volume': 'Option trading volume today',
                'open_interest': 'Total open option contracts',
                'bid_ask_spread': 'Difference between bid and ask',
                'spread_pct': 'Bid-ask spread as % of mid price'
            },
            'interpretation': {
                'low_iv': 'IV < 15% - Market expects low volatility, options are cheap',
                'normal_iv': 'IV 15-25% - Typical market conditions',
                'elevated_iv': 'IV 25-35% - Market expects higher volatility',
                'high_iv': 'IV 35-50% - Significant uncertainty expected',
                'extreme_iv': 'IV > 50% - Extreme volatility expected (rare)'
            }
        },
        'data': results
    }
    
    return output


def main():
    """Main execution function."""
    print("SECTOR ETFs IMPLIED VOLATILITY FETCHER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Fetch snapshot
    snapshot_data = fetch_sector_etfs_snapshot()
    
    # Save snapshot
    snapshot_path = Path(__file__).parent / OUTPUT_CONFIG['snapshot']
    with open(snapshot_path, 'w') as f:
        json.dump(snapshot_data, f, indent=2, default=serialize_for_json)
    print(f"\n✅ Snapshot saved: {snapshot_path}")
    print(f"   Size: {snapshot_path.stat().st_size:,} bytes")
    
    print("\n" + "="*80)
    print("SECTOR ETFs IV FETCH COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
