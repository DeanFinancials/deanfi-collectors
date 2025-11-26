"""
Analyze Individual Ticker Recommendation Trends

This script identifies the top 10 most bullish and top 10 most bearish tickers
based on changes in analyst recommendations over time.

Input: recommendation_trends.json
Output: ticker_trends_analysis.json
"""
import json
import sys
from pathlib import Path
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sector_mapping import get_sector, get_etf_ticker


def calculate_ticker_trends(ticker_data: Dict) -> List[Dict]:
    """
    Calculate trend metrics for each ticker.
    
    Args:
        ticker_data: Dictionary mapping ticker -> list of recommendation periods
        
    Returns:
        List of ticker trend dictionaries with calculated metrics
    """
    trends = []
    
    for ticker, periods in ticker_data.items():
        # Skip tickers with no data or insufficient periods
        if not isinstance(periods, list) or len(periods) < 2:
            continue
        
        # Get latest and oldest periods
        latest = periods[0]
        oldest = periods[-1]
        
        # Skip if missing required fields
        if 'bullish_ratio' not in latest or 'bullish_ratio' not in oldest:
            continue
        
        # Calculate changes
        bullish_change = latest['bullish_ratio'] - oldest['bullish_ratio']
        bearish_change = latest.get('bearish_ratio', 0) - oldest.get('bearish_ratio', 0)
        total_change = latest.get('total_recommendations', 0) - oldest.get('total_recommendations', 0)
        
        # Calculate period-over-period changes
        pop_changes = []
        for i in range(len(periods) - 1):
            curr = periods[i]
            prev = periods[i + 1]
            if 'bullish_ratio' in curr and 'bullish_ratio' in prev:
                pop_changes.append(curr['bullish_ratio'] - prev['bullish_ratio'])
        
        avg_pop_change = sum(pop_changes) / len(pop_changes) if pop_changes else 0
        
        # Determine trend direction
        if bullish_change > 10:
            trend_direction = 'strongly_bullish'
        elif bullish_change > 5:
            trend_direction = 'increasingly_bullish'
        elif bullish_change > 1:
            trend_direction = 'slightly_bullish'
        elif bullish_change < -10:
            trend_direction = 'strongly_bearish'
        elif bullish_change < -5:
            trend_direction = 'increasingly_bearish'
        elif bullish_change < -1:
            trend_direction = 'slightly_bearish'
        else:
            trend_direction = 'stable'
        
        # Get sector info
        sector = get_sector(ticker)
        sector_etf = get_etf_ticker(sector) if sector != 'Unknown' else ''
        
        trend_info = {
            'ticker': ticker,
            'sector': sector,
            'sector_etf': sector_etf,
            'trend': trend_direction,
            'bullish_ratio_change': round(bullish_change, 2),
            'bearish_ratio_change': round(bearish_change, 2),
            'total_recommendations_change': total_change,
            'avg_period_over_period_change': round(avg_pop_change, 2),
            'latest_period': latest.get('period'),
            'latest_bullish_ratio': latest.get('bullish_ratio'),
            'latest_total_recommendations': latest.get('total_recommendations'),
            'oldest_period': oldest.get('period'),
            'oldest_bullish_ratio': oldest.get('bullish_ratio'),
            'num_periods_analyzed': len(periods),
            'latest_breakdown': {
                'strongBuy': latest.get('strongBuy', 0),
                'buy': latest.get('buy', 0),
                'hold': latest.get('hold', 0),
                'sell': latest.get('sell', 0),
                'strongSell': latest.get('strongSell', 0)
            }
        }
        
        trends.append(trend_info)
    
    return trends


def get_top_and_bottom_movers(trends: List[Dict], n: int = 25) -> Tuple[List[Dict], List[Dict]]:
    """
    Get the top N most bullish and bottom N most bearish tickers.
    
    Args:
        trends: List of ticker trend dictionaries
        n: Number of top/bottom tickers to return (default: 25)
        
    Returns:
        Tuple of (top_bullish, top_bearish) lists
    """
    # Sort by bullish_ratio_change
    sorted_trends = sorted(trends, key=lambda x: x['bullish_ratio_change'], reverse=True)
    
    # Top N most bullish (highest positive change)
    top_bullish = sorted_trends[:n]
    
    # Bottom N most bearish (lowest/most negative change)
    top_bearish = sorted_trends[-n:][::-1]  # Reverse to show most bearish first
    
    return top_bullish, top_bearish


def get_statistics(trends: List[Dict]) -> Dict:
    """
    Calculate summary statistics across all tickers.
    
    Args:
        trends: List of ticker trend dictionaries
        
    Returns:
        Dictionary with summary statistics
    """
    if not trends:
        return {}
    
    bullish_changes = [t['bullish_ratio_change'] for t in trends]
    
    # Count by trend category
    trend_counts = {}
    for trend in trends:
        category = trend['trend']
        trend_counts[category] = trend_counts.get(category, 0) + 1
    
    # Calculate stats
    stats = {
        'total_tickers_analyzed': len(trends),
        'avg_bullish_change': round(sum(bullish_changes) / len(bullish_changes), 2),
        'median_bullish_change': round(sorted(bullish_changes)[len(bullish_changes) // 2], 2),
        'max_bullish_change': round(max(bullish_changes), 2),
        'min_bullish_change': round(min(bullish_changes), 2),
        'tickers_improving': len([c for c in bullish_changes if c > 1]),
        'tickers_declining': len([c for c in bullish_changes if c < -1]),
        'tickers_stable': len([c for c in bullish_changes if -1 <= c <= 1]),
        'trend_distribution': trend_counts
    }
    
    return stats


def format_output(top_bullish: List[Dict], top_bearish: List[Dict], 
                 all_trends: List[Dict], metadata: Dict) -> Dict:
    """
    Format the final output JSON structure.
    
    Args:
        top_bullish: Top 10 most bullish tickers
        top_bearish: Top 10 most bearish tickers
        all_trends: All ticker trends
        metadata: Original metadata
        
    Returns:
        Formatted output dictionary
    """
    output = OrderedDict()
    
    # README section
    output['_README'] = {
        'description': 'Top 25 Most Bullish and Bearish S&P 500 Stocks by Analyst Recommendation Change',
        'usage': 'This file identifies individual stocks with the biggest changes in analyst sentiment',
        'navigation': {
            'metadata': 'Information about when and how this analysis was generated',
            'field_descriptions': 'Definitions of all data fields used for each ticker',
            'trend_categories': 'Explanation of the 7 trend classifications',
            'summary_statistics': 'Overall statistics across all 500 stocks analyzed',
            'top_25_most_bullish': 'Stocks with the largest INCREASE in bullish recommendations',
            'top_25_most_bearish': 'Stocks with the largest DECREASE in bullish recommendations'
        },
        'interpretation': 'Positive bullish_ratio_change = analysts becoming more bullish. Negative = becoming more bearish.'
    }
    
    # Metadata
    output['metadata'] = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'Analyzed from recommendation_trends.json',
        'analysis_type': 'Individual Ticker Trends',
        'num_tickers_analyzed': len(all_trends),
        'ranking_criteria': 'Change in bullish ratio from oldest to latest period',
        'original_metadata': metadata
    }
    
    # Field descriptions
    output['field_descriptions'] = {
        'ticker': 'Stock ticker symbol',
        'sector': 'GICS sector name',
        'sector_etf': 'Sector ETF ticker (e.g., XLK, XLV)',
        'trend': 'Overall trend direction classification',
        'bullish_ratio_change': 'Change in bullish ratio (percentage points)',
        'bearish_ratio_change': 'Change in bearish ratio (percentage points)',
        'total_recommendations_change': 'Change in total number of analyst recommendations',
        'avg_period_over_period_change': 'Average change between consecutive periods',
        'latest_bullish_ratio': 'Most recent bullish ratio percentage',
        'oldest_bullish_ratio': 'Oldest bullish ratio percentage in dataset',
        'latest_total_recommendations': 'Current total number of analyst recommendations',
        'num_periods_analyzed': 'Number of time periods analyzed',
        'latest_breakdown': 'Breakdown of latest period recommendations by category'
    }
    
    # Trend categories
    output['trend_categories'] = {
        'strongly_bullish': 'Bullish ratio increased by >10 percentage points',
        'increasingly_bullish': 'Bullish ratio increased by 5-10 percentage points',
        'slightly_bullish': 'Bullish ratio increased by 1-5 percentage points',
        'stable': 'Bullish ratio changed by less than 1 percentage point',
        'slightly_bearish': 'Bullish ratio decreased by 1-5 percentage points',
        'increasingly_bearish': 'Bullish ratio decreased by 5-10 percentage points',
        'strongly_bearish': 'Bullish ratio decreased by >10 percentage points'
    }
    
    # Summary statistics
    output['summary_statistics'] = get_statistics(all_trends)
    
    # Top 25 most bullish
    output['top_25_most_bullish'] = {
        'description': 'Top 25 tickers with the largest increase in bullish analyst recommendations',
        'tickers': top_bullish
    }
    
    # Top 25 most bearish
    output['top_25_most_bearish'] = {
        'description': 'Top 25 tickers with the largest decrease in bullish analyst recommendations',
        'tickers': top_bearish
    }
    
    return output


def main():
    """Main execution function."""
    script_dir = Path(__file__).parent
    input_file = script_dir / 'recommendation_trends.json'
    output_file = script_dir / 'ticker_trends_analysis.json'
    
    print("="*70)
    print("ANALYZE INDIVIDUAL TICKER RECOMMENDATION TRENDS")
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
    
    # Calculate trends for all tickers
    print("📊 Calculating trends for all tickers...")
    all_trends = calculate_ticker_trends(ticker_data)
    print(f"✅ Analyzed {len(all_trends)} tickers with sufficient data")
    print()
    
    # Get top and bottom movers
    print("🔝 Identifying top movers...")
    top_bullish, top_bearish = get_top_and_bottom_movers(all_trends, n=25)
    print(f"✅ Identified top 25 most bullish and top 25 most bearish")
    print()
    
    # Print summary
    stats = get_statistics(all_trends)
    print("Summary Statistics:")
    print("-" * 70)
    print(f"  Total tickers analyzed: {stats['total_tickers_analyzed']}")
    print(f"  Average bullish change: {stats['avg_bullish_change']:+.2f}%")
    print(f"  Tickers improving: {stats['tickers_improving']} ({stats['tickers_improving']/stats['total_tickers_analyzed']*100:.1f}%)")
    print(f"  Tickers stable: {stats['tickers_stable']} ({stats['tickers_stable']/stats['total_tickers_analyzed']*100:.1f}%)")
    print(f"  Tickers declining: {stats['tickers_declining']} ({stats['tickers_declining']/stats['total_tickers_analyzed']*100:.1f}%)")
    print("-" * 70)
    print()
    
    # Print top 25 most bullish
    print("🚀 TOP 25 MOST BULLISH (Largest Increase in Analyst Sentiment):")
    print("-" * 70)
    for i, ticker_info in enumerate(top_bullish, 1):
        ticker = ticker_info['ticker']
        sector_etf = ticker_info['sector_etf']
        change = ticker_info['bullish_ratio_change']
        latest = ticker_info['latest_bullish_ratio']
        total_recs = ticker_info['latest_total_recommendations']
        
        print(f"  {i:2d}. {ticker:6s} ({sector_etf:5s}) {change:+6.2f}% → {latest:5.1f}% bullish ({total_recs} analysts)")
    print("-" * 70)
    print()
    
    # Print top 25 most bearish
    print("📉 TOP 25 MOST BEARISH (Largest Decrease in Analyst Sentiment):")
    print("-" * 70)
    for i, ticker_info in enumerate(top_bearish, 1):
        ticker = ticker_info['ticker']
        sector_etf = ticker_info['sector_etf']
        change = ticker_info['bullish_ratio_change']
        latest = ticker_info['latest_bullish_ratio']
        total_recs = ticker_info['latest_total_recommendations']
        
        print(f"  {i:2d}. {ticker:6s} ({sector_etf:5s}) {change:+6.2f}% → {latest:5.1f}% bullish ({total_recs} analysts)")
    print("-" * 70)
    print()
    
    # Format output
    output_data = format_output(top_bullish, top_bearish, all_trends, metadata)
    
    # Save
    print(f"💾 Writing to {output_file.name}...")
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✅ Saved to {output_file}")
    print()
    print("="*70)


if __name__ == "__main__":
    main()
