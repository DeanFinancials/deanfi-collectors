"""
Fetch implied volatility data for VIX Options.

VIX options are unique - they measure volatility of volatility.
This fetcher tracks VIX option IV to understand options market expectations.

Outputs:
- vix_options_snapshot.json: Current VIX option IV snapshot
- vix_options_historical.json: 252 days of VIX option IV data
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
    format_iv_percentage,
    serialize_for_json,
    get_iv_historical_reference
)

# Load config
CONFIG_PATH = Path(__file__).parent / 'config.yml'
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

VIX_CONFIG = config['vix']
OPTIONS_CRITERIA = config['options_criteria']
OUTPUT_CONFIG = config['output']['vix']


def fetch_vix_snapshot():
    """
    Fetch current IV snapshot for VIX options.
    
    Returns:
        Dict with metadata and VIX option IV data
    """
    print("="*80)
    print("FETCHING VIX OPTIONS IMPLIED VOLATILITY SNAPSHOT")
    print("="*80)
    print(f"Symbol: ^VIX")
    print(f"Timestamp: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    symbol = '^VIX'
    info = VIX_CONFIG[symbol]
    
    print(f"Fetching {symbol} ({info['name']})...", end=' ')
    
    snapshot = get_option_snapshot(
        symbol,
        min_dte=OPTIONS_CRITERIA['min_dte'],
        max_dte=OPTIONS_CRITERIA['max_dte'],
        atm_tolerance=OPTIONS_CRITERIA['atm_tolerance']
    )
    
    if snapshot:
        # Add VIX metadata
        snapshot['name'] = info['name']
        snapshot['description'] = info['description']
        snapshot['note'] = info['note']
        
        # Format IV percentages for display
        snapshot['average_iv_formatted'] = format_iv_percentage(snapshot['average_iv'])
        
        # VIX has extreme IV values - custom classification
        if snapshot['average_iv'] < 0.50:
            iv_level = "Very Low (for VIX)"
        elif snapshot['average_iv'] < 1.00:
            iv_level = "Low"
        elif snapshot['average_iv'] < 1.50:
            iv_level = "Normal"
        elif snapshot['average_iv'] < 2.00:
            iv_level = "Elevated"
        else:
            iv_level = "High"
        
        snapshot['iv_level'] = iv_level
        
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
                f"{((snapshot['average_iv'] / hist_ref['historical_avg'] - 1) * 100):.2f}%",
            'special_note': hist_ref.get('special_note', None)
        }
        
        print(f"✅ IV: {snapshot['average_iv_formatted']} ({iv_level})")
    else:
        print("❌ Failed")
        snapshot = None
    
    # Build output
    output = {
        '_README': {
            'description': 'Implied volatility snapshot for VIX options (volatility of volatility)',
            'data_source': 'yfinance (Yahoo Finance) - VIX options data',
            'update_frequency': 'Real-time (run script to update)',
            'last_updated': datetime.now(ET).isoformat(),
            'symbol': symbol,
            'important_note': 'VIX options measure volatility OF volatility - different from equity options',
            'vix_background': {
                'what_is_vix': 'CBOE Volatility Index - measures S&P 500 30-day expected volatility',
                'vix_range': 'Typically 10-30, can spike to 50+ during crises',
                'vix_options': 'Options on VIX itself - used to hedge or speculate on volatility changes'
            },
            'options_criteria': {
                'min_days_to_expiration': OPTIONS_CRITERIA['min_dte'],
                'max_days_to_expiration': OPTIONS_CRITERIA['max_dte'],
                'atm_tolerance': f"{OPTIONS_CRITERIA['atm_tolerance']*100}%"
            },
            'fields_explanation': {
                'current_price': 'Current VIX level (not a price, but volatility index value)',
                'average_iv': 'Average of ATM VIX call and put implied volatility',
                'average_iv_formatted': 'IV as percentage - NOTE: VIX IV is much higher than equity IV',
                'iv_level': 'Classification specific to VIX (different scale than equities)',
                'atm_call': 'ATM VIX call option details',
                'atm_put': 'ATM VIX put option details'
            },
            'interpretation': {
                'vix_iv_meaning': 'High VIX option IV = Market expects large swings in volatility itself',
                'typical_range': 'VIX option IV typically 80-150% (much higher than equity options)',
                'low_vix_iv': 'IV < 100% - Market expects stable volatility environment',
                'normal_vix_iv': 'IV 100-150% - Normal VIX option volatility',
                'high_vix_iv': 'IV > 150% - Extreme uncertainty about future volatility',
                'vix_term_structure': 'Compare near-term vs longer-term VIX option IV for term structure insights'
            },
            'use_cases': {
                'hedge_volatility': 'VIX options used to hedge against volatility spikes',
                'volatility_trading': 'Traders speculate on volatility changes using VIX options',
                'crisis_indicator': 'Extreme VIX option IV can signal market stress'
            }
        },
        'data': {symbol: snapshot} if snapshot else {}
    }
    
    return output


def main():
    """Main execution function."""
    print("VIX OPTIONS IMPLIED VOLATILITY FETCHER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Fetch snapshot
    snapshot_data = fetch_vix_snapshot()
    
    # Save snapshot
    snapshot_path = Path(__file__).parent / OUTPUT_CONFIG['snapshot']
    with open(snapshot_path, 'w') as f:
        json.dump(snapshot_data, f, indent=2, default=serialize_for_json)
    print(f"\n✅ Snapshot saved: {snapshot_path}")
    print(f"   Size: {snapshot_path.stat().st_size:,} bytes")
    
    print("\n" + "="*80)
    print("VIX OPTIONS IV FETCH COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
