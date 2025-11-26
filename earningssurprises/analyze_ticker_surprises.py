#!/usr/bin/env python3
"""
Ticker Earnings Surprises Analyzer
==================================
Analyzes individual ticker earnings performance with advanced metrics.

Metrics Tracked:
- Average surprise percent across all quarters
- Beat rate (% of quarters beating estimates)
- Beat streak (consecutive quarters beating)
- Trend direction (improving/declining surprises)
- Consistency score (standard deviation)
- Most recent quarter performance

Output: Top 25 best performers and bottom 25 worst performers
"""

import json
import sys
import yaml
from pathlib import Path
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sector_mapping import TICKER_TO_SECTOR


class TickerSurprisesAnalyzer:
    """Analyzes ticker-level earnings surprises with comprehensive metrics."""
    
    def __init__(self, config_path="config.yml"):
        """Initialize analyzer with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.top_n = self.config['analysis']['top_movers_count']
        self.thresholds = self.config['surprise_classification']
    
    def load_earnings_data(self, input_file):
        """Load raw earnings data from JSON file."""
        with open(input_file, 'r') as f:
            data = json.load(f)
        return data['data']
    
    def classify_surprise(self, surprise_percent):
        """Classify earnings surprise into category."""
        if surprise_percent is None:
            return "unknown"
        
        if surprise_percent > self.thresholds['strong_beat_threshold']:
            return "strong_beat"
        elif surprise_percent > self.thresholds['beat_threshold']:
            return "beat"
        elif abs(surprise_percent) <= self.thresholds['meet_threshold']:
            return "meet"
        elif surprise_percent >= self.thresholds['miss_threshold']:
            return "miss"
        else:
            return "strong_miss"
    
    def calculate_beat_streak(self, quarters_data):
        """
        Calculate current beat streak (consecutive quarters beating estimates).
        
        Returns:
            Positive number for beat streak, negative for miss streak, 0 for no streak
        """
        # Sort by period (most recent first)
        sorted_quarters = sorted(quarters_data, key=lambda x: x.get('period', ''), reverse=True)
        
        if not sorted_quarters:
            return 0
        
        streak = 0
        last_category = None
        
        for q in sorted_quarters:
            surprise_pct = q.get('surprisePercent')
            if surprise_pct is None:
                break
            
            category = self.classify_surprise(surprise_pct)
            
            if category in ['strong_beat', 'beat']:
                if last_category is None or last_category in ['strong_beat', 'beat']:
                    streak += 1
                    last_category = 'beat'
                else:
                    break
            elif category in ['miss', 'strong_miss']:
                if last_category is None or last_category in ['miss', 'strong_miss']:
                    streak -= 1
                    last_category = 'miss'
                else:
                    break
            else:  # meet
                break
        
        return streak
    
    def calculate_trend_direction(self, quarters_data):
        """
        Calculate trend direction (improving/declining/stable).
        
        Compares older quarters to recent quarters.
        Returns: "improving", "declining", or "stable"
        """
        if len(quarters_data) < 2:
            return "insufficient_data"
        
        # Sort by period
        sorted_quarters = sorted(quarters_data, key=lambda x: x.get('period', ''))
        surprises = [q.get('surprisePercent') for q in sorted_quarters if q.get('surprisePercent') is not None]
        
        if len(surprises) < 2:
            return "insufficient_data"
        
        # Split into older half and recent half
        mid = len(surprises) // 2
        older_avg = mean(surprises[:mid])
        recent_avg = mean(surprises[mid:])
        
        diff = recent_avg - older_avg
        
        # Use a threshold to determine significance
        if diff > 2.0:
            return "improving"
        elif diff < -2.0:
            return "declining"
        else:
            return "stable"
    
    def analyze_ticker(self, ticker, quarters_data):
        """
        Comprehensive analysis of a single ticker's earnings surprises.
        
        Returns:
            Dictionary with all calculated metrics
        """
        if not quarters_data:
            return None
        
        # Extract surprise percentages
        surprises = [q.get('surprisePercent') for q in quarters_data if q.get('surprisePercent') is not None]
        
        if not surprises:
            return None
        
        # Calculate basic statistics
        avg_surprise = mean(surprises)
        
        # Calculate beat rate
        beats = sum(1 for s in surprises if s > self.thresholds['beat_threshold'])
        beat_rate = (beats / len(surprises)) * 100
        
        # Calculate consistency (lower stdev = more consistent)
        consistency_score = stdev(surprises) if len(surprises) > 1 else 0
        
        # Get beat streak
        beat_streak = self.calculate_beat_streak(quarters_data)
        
        # Get trend direction
        trend = self.calculate_trend_direction(quarters_data)
        
        # Get most recent quarter info
        most_recent = max(quarters_data, key=lambda x: x.get('period', ''))
        
        # Count categories
        categories = [self.classify_surprise(s) for s in surprises]
        category_counts = {
            'strong_beat': categories.count('strong_beat'),
            'beat': categories.count('beat'),
            'meet': categories.count('meet'),
            'miss': categories.count('miss'),
            'strong_miss': categories.count('strong_miss')
        }
        
        return {
            'ticker': ticker,
            'sector': TICKER_TO_SECTOR.get(ticker, 'Unknown'),
            'quarters_analyzed': len(quarters_data),
            'average_surprise_percent': round(avg_surprise, 2),
            'beat_rate': round(beat_rate, 1),
            'beat_streak': beat_streak,
            'trend_direction': trend,
            'consistency_score': round(consistency_score, 2),
            'most_recent_quarter': {
                'period': most_recent.get('period'),
                'quarter': most_recent.get('quarter'),
                'year': most_recent.get('year'),
                'surprise_percent': most_recent.get('surprisePercent'),
                'category': self.classify_surprise(most_recent.get('surprisePercent'))
            },
            'category_breakdown': category_counts,
            'quarterly_details': [
                {
                    'period': q.get('period'),
                    'quarter': q.get('quarter'),
                    'year': q.get('year'),
                    'actual': q.get('actual'),
                    'estimate': q.get('estimate'),
                    'surprise': q.get('surprise'),
                    'surprise_percent': q.get('surprisePercent'),
                    'category': self.classify_surprise(q.get('surprisePercent'))
                }
                for q in sorted(quarters_data, key=lambda x: x.get('period', ''), reverse=True)
            ]
        }
    
    def get_top_and_bottom_movers(self, ticker_analyses, n=25):
        """
        Get top N and bottom N tickers by average surprise percent.
        
        Args:
            ticker_analyses: List of ticker analysis dictionaries
            n: Number of top/bottom to return
            
        Returns:
            Tuple of (top_movers, bottom_movers)
        """
        # Sort by average surprise percent
        sorted_tickers = sorted(ticker_analyses, key=lambda x: x['average_surprise_percent'], reverse=True)
        
        top_movers = sorted_tickers[:n]
        bottom_movers = sorted_tickers[-n:][::-1]  # Reverse to show worst first
        
        return top_movers, bottom_movers
    
    def calculate_summary_stats(self, ticker_analyses):
        """Calculate overall summary statistics."""
        avg_surprises = [t['average_surprise_percent'] for t in ticker_analyses]
        beat_rates = [t['beat_rate'] for t in ticker_analyses]
        
        # Count trend directions
        trends = [t['trend_direction'] for t in ticker_analyses]
        
        return {
            'total_tickers_analyzed': len(ticker_analyses),
            'overall_average_surprise': round(mean(avg_surprises), 2),
            'median_surprise': round(sorted(avg_surprises)[len(avg_surprises)//2], 2),
            'overall_beat_rate': round(mean(beat_rates), 1),
            'trend_breakdown': {
                'improving': trends.count('improving'),
                'declining': trends.count('declining'),
                'stable': trends.count('stable'),
                'insufficient_data': trends.count('insufficient_data')
            },
            'best_performer': max(avg_surprises),
            'worst_performer': min(avg_surprises)
        }
    
    def save_to_json(self, top_movers, bottom_movers, summary_stats, output_file):
        """Save analysis to JSON with detailed README."""
        
        readme = {
            "_README": {
                "description": "Individual ticker earnings surprise analysis with performance metrics",
                "purpose": "Identify best and worst earnings performers with advanced metrics",
                
                "data_sections": {
                    "summary_statistics": "Overall market statistics across all S&P 500 companies",
                    "top_25_best_performers": f"Top {self.top_n} companies with highest average earnings surprises",
                    "top_25_worst_performers": f"Bottom {self.top_n} companies with lowest average earnings surprises"
                },
                
                "key_metrics_explained": {
                    "average_surprise_percent": "Mean earnings surprise % across last 4 quarters",
                    "beat_rate": "Percentage of quarters where company beat estimates (0-100%)",
                    "beat_streak": "Consecutive quarters beating (positive) or missing (negative) estimates",
                    "trend_direction": "improving/declining/stable based on recent vs older quarters",
                    "consistency_score": "Standard deviation of surprises (lower = more consistent)",
                    "most_recent_quarter": "Performance in the most recently reported quarter",
                    "category_breakdown": "Count of quarters in each surprise category"
                },
                
                "surprise_categories": {
                    "strong_beat": f"Surprise > {self.thresholds['strong_beat_threshold']}%",
                    "beat": f"Surprise 0% to {self.thresholds['strong_beat_threshold']}%",
                    "meet": f"Surprise within ± {self.thresholds['meet_threshold']}%",
                    "miss": f"Surprise {self.thresholds['miss_threshold']}% to 0%",
                    "strong_miss": f"Surprise < {self.thresholds['miss_threshold']}%"
                },
                
                "interpretation_guide": {
                    "beat_streak": {
                        "positive_number": "Company has beaten estimates for N consecutive quarters",
                        "negative_number": "Company has missed estimates for N consecutive quarters",
                        "zero": "No current streak (last quarter was 'meet' or mixed pattern)"
                    },
                    "trend_direction": {
                        "improving": "Recent quarters show better surprises than older quarters (>2% improvement)",
                        "declining": "Recent quarters show worse surprises than older quarters (>2% decline)",
                        "stable": "No significant trend in surprise direction",
                        "insufficient_data": "Not enough quarters to determine trend"
                    },
                    "consistency_score": {
                        "low_0_5": "Very consistent earnings surprises",
                        "medium_5_10": "Moderate variability in surprises",
                        "high_10_plus": "High variability - unpredictable surprises"
                    }
                },
                
                "usage_examples": {
                    "finding_consistent_beaters": "Filter for beat_rate >75% AND consistency_score <5",
                    "momentum_plays": "Look for beat_streak >=3 AND trend_direction='improving'",
                    "turnaround_candidates": "Companies in bottom 25 with trend_direction='improving'",
                    "avoid_misses": "Companies with beat_streak <=-2 may continue missing"
                }
            }
        }
        
        output = {
            **readme,
            "metadata": {
                "data_source": "Finnhub Earnings Surprises API",
                "analysis_type": "Individual Ticker Performance",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "quarters_analyzed": 4,
                "top_movers_count": self.top_n
            },
            "summary_statistics": summary_stats,
            "top_25_best_performers": top_movers,
            "top_25_worst_performers": bottom_movers
        }
        
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        file_size = Path(output_file).stat().st_size
        print(f"\n✓ Ticker analysis saved to {output_file}")
        print(f"  File size: {file_size:,} bytes")


def main():
    """Main execution function."""
    print("=" * 70)
    print("ANALYZING TICKER EARNINGS SURPRISES")
    print("=" * 70)
    
    analyzer = TickerSurprisesAnalyzer()
    
    # Load raw earnings data
    input_file = analyzer.config['output']['raw_data']
    print(f"\nLoading data from {input_file}...")
    earnings_data = analyzer.load_earnings_data(input_file)
    print(f"✓ Loaded data for {len(earnings_data)} tickers")
    
    # Analyze each ticker
    print("\nAnalyzing individual tickers...")
    ticker_analyses = []
    for ticker, quarters_data in earnings_data.items():
        analysis = analyzer.analyze_ticker(ticker, quarters_data)
        if analysis:
            ticker_analyses.append(analysis)
    
    print(f"✓ Analyzed {len(ticker_analyses)} tickers")
    
    # Get top and bottom movers
    print(f"\nIdentifying top {analyzer.top_n} and bottom {analyzer.top_n} performers...")
    top_movers, bottom_movers = analyzer.get_top_and_bottom_movers(ticker_analyses, analyzer.top_n)
    
    # Calculate summary statistics
    summary_stats = analyzer.calculate_summary_stats(ticker_analyses)
    
    # Save to JSON
    output_file = analyzer.config['output']['ticker_analysis']
    analyzer.save_to_json(top_movers, bottom_movers, summary_stats, output_file)
    
    # Print summary
    print("\n" + "=" * 70)
    print("TOP 10 BEST PERFORMERS (by avg surprise %)")
    print("=" * 70)
    for i, ticker_data in enumerate(top_movers[:10], 1):
        print(f"{i:2d}. {ticker_data['ticker']:6s} | Avg: {ticker_data['average_surprise_percent']:+7.2f}% | "
              f"Beat Rate: {ticker_data['beat_rate']:5.1f}% | Streak: {ticker_data['beat_streak']:+3d} | "
              f"Trend: {ticker_data['trend_direction']}")
    
    print("\n" + "=" * 70)
    print("TOP 10 WORST PERFORMERS (by avg surprise %)")
    print("=" * 70)
    for i, ticker_data in enumerate(bottom_movers[:10], 1):
        print(f"{i:2d}. {ticker_data['ticker']:6s} | Avg: {ticker_data['average_surprise_percent']:+7.2f}% | "
              f"Beat Rate: {ticker_data['beat_rate']:5.1f}% | Streak: {ticker_data['beat_streak']:+3d} | "
              f"Trend: {ticker_data['trend_direction']}")
    
    print("\n" + "=" * 70)
    print("OVERALL STATISTICS")
    print("=" * 70)
    print(f"Total tickers analyzed: {summary_stats['total_tickers_analyzed']}")
    print(f"Overall average surprise: {summary_stats['overall_average_surprise']:+.2f}%")
    print(f"Overall beat rate: {summary_stats['overall_beat_rate']:.1f}%")
    print(f"Trends - Improving: {summary_stats['trend_breakdown']['improving']}, "
          f"Declining: {summary_stats['trend_breakdown']['declining']}, "
          f"Stable: {summary_stats['trend_breakdown']['stable']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
