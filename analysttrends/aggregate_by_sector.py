"""
Aggregate Recommendation Trends by GICS Sector

This script reads the individual ticker recommendation data and aggregates it by sector.
It also calculates trend analysis to show if analyst sentiment is becoming more bullish or bearish.

Input: recommendation_trends.json
Output: sector_recommendation_trends.json
"""
import json
import sys
from pathlib import Path
from collections import defaultdict, OrderedDict
from datetime import datetime
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sector_mapping import (
    get_sector, 
    get_etf_ticker, 
    SECTOR_TO_ETF,
    get_tickers_by_sector
)


def aggregate_by_sector(ticker_data: Dict) -> Dict:
    """
    Aggregate recommendation data by sector.
    
    Args:
        ticker_data: Dictionary mapping ticker -> list of recommendation periods
        
    Returns:
        Dictionary mapping sector -> aggregated recommendation data
    """
    # Initialize sector aggregates
    sector_data = defaultdict(lambda: defaultdict(lambda: {
        'strongBuy': 0,
        'buy': 0,
        'hold': 0,
        'sell': 0,
        'strongSell': 0,
        'ticker_count': 0,
        'tickers': []
    }))
    
    # Aggregate by sector and period
    for ticker, periods in ticker_data.items():
        # Skip tickers with no data
        if not isinstance(periods, list) or len(periods) == 0:
            continue
        
        sector = get_sector(ticker)
        if sector == 'Unknown':
            print(f"⚠️  Unknown sector for {ticker}, skipping...")
            continue
        
        # Process each period
        for period_data in periods:
            period = period_data.get('period')
            if not period:
                continue
            
            # Add to sector aggregate
            sector_data[sector][period]['strongBuy'] += period_data.get('strongBuy', 0)
            sector_data[sector][period]['buy'] += period_data.get('buy', 0)
            sector_data[sector][period]['hold'] += period_data.get('hold', 0)
            sector_data[sector][period]['sell'] += period_data.get('sell', 0)
            sector_data[sector][period]['strongSell'] += period_data.get('strongSell', 0)
            sector_data[sector][period]['ticker_count'] += 1
            
            if ticker not in sector_data[sector][period]['tickers']:
                sector_data[sector][period]['tickers'].append(ticker)
    
    # Convert to regular dict and sort periods
    result = {}
    for sector, periods in sector_data.items():
        # Sort periods in reverse chronological order (newest first)
        sorted_periods = sorted(periods.items(), key=lambda x: x[0], reverse=True)
        
        result[sector] = []
        for period, data in sorted_periods:
            # Calculate metrics
            total = (data['strongBuy'] + data['buy'] + data['hold'] + 
                    data['sell'] + data['strongSell'])
            
            bullish = data['strongBuy'] + data['buy']
            bearish = data['sell'] + data['strongSell']
            
            period_data = {
                'period': period,
                'strongBuy': data['strongBuy'],
                'buy': data['buy'],
                'hold': data['hold'],
                'sell': data['sell'],
                'strongSell': data['strongSell'],
                'total_recommendations': total,
                'bullish_recommendations': bullish,
                'bearish_recommendations': bearish,
                'bullish_ratio': round((bullish / total * 100) if total > 0 else 0, 2),
                'bearish_ratio': round((bearish / total * 100) if total > 0 else 0, 2),
                'ticker_count': data['ticker_count'],
                'avg_recommendations_per_ticker': round(total / data['ticker_count'], 2) if data['ticker_count'] > 0 else 0
            }
            result[sector].append(period_data)
    
    return result


def calculate_trends(sector_data: Dict) -> Dict:
    """
    Calculate trend analysis for each sector.
    
    Args:
        sector_data: Dictionary mapping sector -> list of period data
        
    Returns:
        Dictionary mapping sector -> trend analysis
    """
    trends = {}
    
    for sector, periods in sector_data.items():
        if len(periods) < 2:
            trends[sector] = {
                'trend': 'insufficient_data',
                'message': 'Need at least 2 periods to calculate trend'
            }
            continue
        
        # Compare most recent period to oldest period
        latest = periods[0]  # Already sorted newest first
        oldest = periods[-1]
        
        # Calculate changes
        bullish_change = latest['bullish_ratio'] - oldest['bullish_ratio']
        bearish_change = latest['bearish_ratio'] - oldest['bearish_ratio']
        total_change = latest['total_recommendations'] - oldest['total_recommendations']
        
        # Calculate period-over-period changes
        pop_changes = []
        for i in range(len(periods) - 1):
            curr = periods[i]
            prev = periods[i + 1]
            pop_changes.append(curr['bullish_ratio'] - prev['bullish_ratio'])
        
        avg_pop_change = sum(pop_changes) / len(pop_changes) if pop_changes else 0
        
        # Determine trend
        if bullish_change > 5:
            trend_direction = 'increasingly_bullish'
        elif bullish_change > 1:
            trend_direction = 'slightly_bullish'
        elif bullish_change < -5:
            trend_direction = 'increasingly_bearish'
        elif bullish_change < -1:
            trend_direction = 'slightly_bearish'
        else:
            trend_direction = 'stable'
        
        trends[sector] = {
            'trend': trend_direction,
            'bullish_ratio_change': round(bullish_change, 2),
            'bearish_ratio_change': round(bearish_change, 2),
            'total_recommendations_change': total_change,
            'avg_period_over_period_change': round(avg_pop_change, 2),
            'latest_bullish_ratio': latest['bullish_ratio'],
            'oldest_bullish_ratio': oldest['bullish_ratio'],
            'num_periods_analyzed': len(periods)
        }
    
    return trends


def format_output(sector_data: Dict, trends: Dict, metadata: Dict) -> Dict:
    """
    Format the final output JSON structure.
    
    Args:
        sector_data: Aggregated sector data
        trends: Trend analysis
        metadata: Original metadata
        
    Returns:
        Formatted output dictionary
    """
    output = OrderedDict()
    
    # Update metadata
    output['_README'] = {
        'description': 'S&P 500 Analyst Recommendations Aggregated by GICS Sector',
        'usage': 'This file contains analyst recommendation trends aggregated at the sector level',
        'navigation': {
            'metadata': 'Information about when and how this data was generated',
            'field_descriptions': 'Definitions of all data fields used throughout this file',
            'trend_categories': 'Explanation of trend classifications (increasingly_bullish, stable, etc.)',
            'sectors': 'Main data section - contains all 11 GICS sectors with their recommendation trends'
        },
        'how_to_read_sectors': 'Each sector contains: (1) sector_name and etf_ticker, (2) trend_analysis showing overall direction, (3) periods array with detailed recommendation data over time'
    }
    
    output['metadata'] = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'Aggregated from recommendation_trends.json',
        'aggregation_level': 'GICS Sector',
        'num_sectors': len(sector_data),
        'num_periods': metadata.get('num_periods_per_ticker', 3),
        'original_metadata': metadata
    }
    
    # Field descriptions
    output['field_descriptions'] = {
        'period': 'Period for the recommendation data (YYYY-MM-DD format)',
        'strongBuy': 'Total Strong Buy recommendations across all tickers in sector',
        'buy': 'Total Buy recommendations across all tickers in sector',
        'hold': 'Total Hold recommendations across all tickers in sector',
        'sell': 'Total Sell recommendations across all tickers in sector',
        'strongSell': 'Total Strong Sell recommendations across all tickers in sector',
        'total_recommendations': 'Sum of all recommendation categories',
        'bullish_recommendations': 'Sum of strongBuy + buy',
        'bearish_recommendations': 'Sum of sell + strongSell',
        'bullish_ratio': 'Percentage of bullish recommendations',
        'bearish_ratio': 'Percentage of bearish recommendations',
        'ticker_count': 'Number of tickers with data in this period',
        'avg_recommendations_per_ticker': 'Average number of analyst recommendations per ticker',
        'trend': 'Overall trend direction based on bullish ratio changes',
        'bullish_ratio_change': 'Change in bullish ratio from oldest to latest period',
        'avg_period_over_period_change': 'Average change in bullish ratio between consecutive periods'
    }
    
    # Trend categories explanation
    output['trend_categories'] = {
        'increasingly_bullish': 'Bullish ratio increased by >5 percentage points',
        'slightly_bullish': 'Bullish ratio increased by 1-5 percentage points',
        'stable': 'Bullish ratio changed by less than 1 percentage point',
        'slightly_bearish': 'Bullish ratio decreased by 1-5 percentage points',
        'increasingly_bearish': 'Bullish ratio decreased by >5 percentage points'
    }
    
    # Sector data
    output['sectors'] = OrderedDict()
    
    # Sort sectors by ETF ticker
    for sector in sorted(sector_data.keys(), key=lambda s: SECTOR_TO_ETF.get(s, s)):
        etf_ticker = get_etf_ticker(sector)
        tickers_in_sector = get_tickers_by_sector(sector)
        
        output['sectors'][etf_ticker] = {
            'sector_name': sector,
            'etf_ticker': etf_ticker,
            'total_tickers_in_sector': len(tickers_in_sector),
            'trend_analysis': trends.get(sector, {}),
            'periods': sector_data[sector]
        }
    
    return output


def main():
    """Main execution function."""
    script_dir = Path(__file__).parent
    input_file = script_dir / 'recommendation_trends.json'
    output_file = script_dir / 'sector_recommendation_trends.json'
    
    print("="*70)
    print("AGGREGATE RECOMMENDATION TRENDS BY SECTOR")
    print("="*70)
    print()
    
    # Load ticker data
    print(f"📂 Loading data from {input_file.name}...")
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    ticker_data = data.get('data', {})
    metadata = data.get('metadata', {})
    
    print(f"✅ Loaded {len(ticker_data)} tickers")
    print()
    
    # Aggregate by sector
    print("📊 Aggregating by sector...")
    sector_data = aggregate_by_sector(ticker_data)
    print(f"✅ Aggregated into {len(sector_data)} sectors")
    print()
    
    # Calculate trends
    print("📈 Calculating trend analysis...")
    trends = calculate_trends(sector_data)
    print("✅ Trend analysis complete")
    print()
    
    # Print summary
    print("Sector Summary:")
    print("-" * 70)
    for sector in sorted(sector_data.keys(), key=lambda s: SECTOR_TO_ETF.get(s, s)):
        etf = get_etf_ticker(sector)
        trend_info = trends.get(sector, {})
        trend = trend_info.get('trend', 'unknown')
        change = trend_info.get('bullish_ratio_change', 0)
        latest_bullish = trend_info.get('latest_bullish_ratio', 0)
        
        trend_emoji = {
            'increasingly_bullish': '📈',
            'slightly_bullish': '↗️ ',
            'stable': '➡️ ',
            'slightly_bearish': '↘️ ',
            'increasingly_bearish': '📉'
        }.get(trend, '❓')
        
        print(f"  {etf:6s} {sector:30s} {trend_emoji} {trend:20s} "
              f"(Bullish: {latest_bullish:5.1f}%, Δ: {change:+.1f}%)")
    
    print("-" * 70)
    print()
    
    # Format output
    output_data = format_output(sector_data, trends, metadata)
    
    # Save
    print(f"💾 Writing to {output_file.name}...")
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✅ Saved to {output_file}")
    print()
    print("="*70)


if __name__ == "__main__":
    main()
