#!/usr/bin/env python3
"""
Sector Earnings Surprises Aggregator
====================================
Aggregates earnings surprise data by GICS sector with quarter-by-quarter analysis.

Key Features:
- Quarter-by-quarter comparison (Q1 vs Q1, Q2 vs Q2, etc.)
- Beat/Miss/Meet rates per sector per quarter
- Average surprise percent by sector
- Most recent quarter highlighted
- Trend analysis across quarters

Input: earnings_surprises.json
Output: sector_earnings_surprises.json
"""

import json
import sys
import yaml
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sector_mapping import TICKER_TO_SECTOR, SECTOR_TO_ETF


class SectorEarningsAggregator:
    """Aggregates earnings surprises by sector with quarterly breakdowns."""
    
    def __init__(self, config_path="config.yml"):
        """Initialize aggregator with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Load surprise classification thresholds
        self.thresholds = self.config['surprise_classification']
    
    def classify_surprise(self, surprise_percent):
        """
        Classify earnings surprise into categories.
        
        Args:
            surprise_percent: Surprise percentage value
            
        Returns:
            Category string: strong_beat, beat, meet, miss, strong_miss
        """
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
    
    def load_earnings_data(self, input_file):
        """Load raw earnings data from JSON file."""
        with open(input_file, 'r') as f:
            data = json.load(f)
        return data['data']
    
    def aggregate_by_sector_and_quarter(self, earnings_data):
        """
        Aggregate earnings data by sector and quarter.
        
        Returns:
            Dictionary with sector -> quarter -> aggregated metrics
        """
        # Structure: sector -> quarter -> list of surprises
        sector_quarters = defaultdict(lambda: defaultdict(list))
        
        # Organize data by sector and quarter
        for ticker, quarters in earnings_data.items():
            sector = TICKER_TO_SECTOR.get(ticker)
            if not sector:
                continue
            
            for q_data in quarters:
                quarter = q_data.get('quarter')
                year = q_data.get('year')
                surprise_pct = q_data.get('surprisePercent')
                
                if quarter is None or surprise_pct is None:
                    continue
                
                # Store all relevant data for this quarter
                sector_quarters[sector][quarter].append({
                    'ticker': ticker,
                    'year': year,
                    'period': q_data.get('period'),
                    'actual': q_data.get('actual'),
                    'estimate': q_data.get('estimate'),
                    'surprise': q_data.get('surprise'),
                    'surprise_percent': surprise_pct,
                    'category': self.classify_surprise(surprise_pct)
                })
        
        return sector_quarters
    
    def calculate_quarter_metrics(self, surprises_list):
        """
        Calculate aggregate metrics for a quarter's surprises.
        
        Args:
            surprises_list: List of surprise data dicts
            
        Returns:
            Dictionary of calculated metrics
        """
        if not surprises_list:
            return None
        
        total_count = len(surprises_list)
        
        # Count categories
        category_counts = defaultdict(int)
        for item in surprises_list:
            category_counts[item['category']] += 1
        
        # Calculate surprise statistics
        surprise_values = [item['surprise_percent'] for item in surprises_list]
        avg_surprise = sum(surprise_values) / len(surprise_values)
        
        # Calculate beat/miss/meet rates
        beat_count = category_counts['strong_beat'] + category_counts['beat']
        meet_count = category_counts['meet']
        miss_count = category_counts['miss'] + category_counts['strong_miss']
        
        return {
            'total_companies': total_count,
            'average_surprise_percent': round(avg_surprise, 2),
            'beat_rate': round((beat_count / total_count) * 100, 1),
            'meet_rate': round((meet_count / total_count) * 100, 1),
            'miss_rate': round((miss_count / total_count) * 100, 1),
            'strong_beat_count': category_counts['strong_beat'],
            'beat_count': category_counts['beat'],
            'meet_count': category_counts['meet'],
            'miss_count': category_counts['miss'],
            'strong_miss_count': category_counts['strong_miss'],
            'median_surprise_percent': round(sorted(surprise_values)[len(surprise_values)//2], 2),
            'max_surprise_percent': round(max(surprise_values), 2),
            'min_surprise_percent': round(min(surprise_values), 2)
        }
    
    def get_most_recent_quarter(self, earnings_data):
        """Determine the most recent quarter from the dataset."""
        max_period = None
        max_quarter = None
        max_year = None
        
        for ticker, quarters in earnings_data.items():
            for q_data in quarters:
                period = q_data.get('period')
                if period and (max_period is None or period > max_period):
                    max_period = period
                    max_quarter = q_data.get('quarter')
                    max_year = q_data.get('year')
        
        return max_quarter, max_year, max_period
    
    def format_output(self, sector_quarters, most_recent_quarter, most_recent_year):
        """Format aggregated data for JSON output."""
        output_sectors = {}
        
        for sector, quarters_data in sorted(sector_quarters.items()):
            sector_info = {
                'sector_name': sector,
                'etf_symbol': SECTOR_TO_ETF.get(sector, 'N/A'),
                'quarters': {}
            }
            
            # Process each quarter (Q1, Q2, Q3, Q4)
            for quarter in sorted(quarters_data.keys()):
                metrics = self.calculate_quarter_metrics(quarters_data[quarter])
                
                if metrics:
                    quarter_key = f"Q{quarter}"
                    sector_info['quarters'][quarter_key] = {
                        **metrics,
                        'is_most_recent': (quarter == most_recent_quarter)
                    }
            
            # Calculate overall sector statistics (across all quarters)
            all_surprises = []
            for quarter_data in quarters_data.values():
                all_surprises.extend(quarter_data)
            
            overall_metrics = self.calculate_quarter_metrics(all_surprises)
            sector_info['overall_statistics'] = overall_metrics
            
            output_sectors[sector] = sector_info
        
        return output_sectors
    
    def save_to_json(self, sector_data, most_recent_quarter, most_recent_year, most_recent_period, output_file):
        """Save sector aggregation to JSON with detailed README."""
        
        readme = {
            "_README": {
                "description": "Earnings surprises aggregated by GICS sector with quarter-by-quarter breakdown",
                "purpose": "Compare sector performance across fiscal quarters to identify trends and patterns",
                "data_organization": "Each sector contains quarterly breakdowns (Q1, Q2, Q3, Q4) plus overall statistics",
                "most_recent_quarter": f"Q{most_recent_quarter} {most_recent_year} (period ending {most_recent_period})",
                
                "usage_guide": {
                    "quarter_comparison": "Compare Q1 across sectors to see which sectors perform best in Q1, etc.",
                    "trend_analysis": "Look at a single sector across Q1->Q2->Q3->Q4 to identify seasonal patterns",
                    "beat_rates": "Higher beat_rate = more companies in sector beating estimates",
                    "surprise_direction": "Positive average_surprise_percent = sector beating estimates on average"
                },
                
                "key_metrics_explained": {
                    "total_companies": "Number of S&P 500 companies in this sector reporting this quarter",
                    "average_surprise_percent": "Mean earnings surprise % across all companies in sector",
                    "beat_rate": "Percentage of companies that beat estimates (beat + strong_beat)",
                    "meet_rate": "Percentage of companies that met estimates (within ±0.5%)",
                    "miss_rate": "Percentage of companies that missed estimates (miss + strong_miss)",
                    "strong_beat_count": "Companies with >5% positive surprise",
                    "beat_count": "Companies with 0-5% positive surprise",
                    "meet_count": "Companies within ±0.5% of estimates",
                    "miss_count": "Companies with 0% to -5% negative surprise",
                    "strong_miss_count": "Companies with <-5% negative surprise",
                    "median_surprise_percent": "Median surprise (less affected by outliers than average)",
                    "max_surprise_percent": "Largest positive surprise in the sector/quarter",
                    "min_surprise_percent": "Largest negative surprise in the sector/quarter",
                    "is_most_recent": "True if this is the most recently reported quarter"
                },
                
                "interpretation_tips": {
                    "comparing_quarters": "Technology (XLK) Q1 vs Healthcare (XLV) Q1 shows which sector had better Q1 performance",
                    "seasonal_patterns": "Some sectors perform better in specific quarters (e.g., Retail in Q4)",
                    "beat_rate_threshold": "Beat rate >60% suggests strong sector momentum",
                    "surprise_consistency": "Low difference between median and average = consistent sector performance",
                    "recent_vs_historical": "Compare most_recent quarter to other quarters for trend direction"
                },
                
                "sectors": list(SECTOR_TO_ETF.keys())
            }
        }
        
        output = {
            **readme,
            "metadata": {
                "data_source": "Finnhub Earnings Surprises API",
                "aggregation_level": "GICS Sector",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_sectors": len(sector_data),
                "most_recent_quarter": f"Q{most_recent_quarter}",
                "most_recent_year": most_recent_year,
                "most_recent_period": most_recent_period,
                "quarters_analyzed": ["Q1", "Q2", "Q3", "Q4"]
            },
            "surprise_classification": {
                "strong_beat": f"> {self.thresholds['strong_beat_threshold']}%",
                "beat": f"0% to {self.thresholds['strong_beat_threshold']}%",
                "meet": f"± {self.thresholds['meet_threshold']}%",
                "miss": f"{self.thresholds['miss_threshold']}% to 0%",
                "strong_miss": f"< {self.thresholds['miss_threshold']}%"
            },
            "sectors": sector_data
        }
        
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        file_size = Path(output_file).stat().st_size
        print(f"\n✓ Sector aggregation saved to {output_file}")
        print(f"  File size: {file_size:,} bytes")
        print(f"  Sectors: {len(sector_data)}")


def main():
    """Main execution function."""
    print("=" * 70)
    print("AGGREGATING EARNINGS SURPRISES BY SECTOR")
    print("=" * 70)
    
    aggregator = SectorEarningsAggregator()
    
    # Load raw earnings data
    input_file = aggregator.config['output']['raw_data']
    print(f"\nLoading data from {input_file}...")
    earnings_data = aggregator.load_earnings_data(input_file)
    print(f"✓ Loaded data for {len(earnings_data)} tickers")
    
    # Get most recent quarter info
    most_recent_q, most_recent_y, most_recent_p = aggregator.get_most_recent_quarter(earnings_data)
    print(f"✓ Most recent quarter: Q{most_recent_q} {most_recent_y} (period: {most_recent_p})")
    
    # Aggregate by sector and quarter
    print("\nAggregating by sector and quarter...")
    sector_quarters = aggregator.aggregate_by_sector_and_quarter(earnings_data)
    
    # Format output
    print("Calculating metrics...")
    sector_data = aggregator.format_output(sector_quarters, most_recent_q, most_recent_y)
    
    # Save to JSON
    output_file = aggregator.config['output']['sector_aggregation']
    aggregator.save_to_json(sector_data, most_recent_q, most_recent_y, most_recent_p, output_file)
    
    # Print summary
    print("\n" + "=" * 70)
    print("SECTOR AGGREGATION SUMMARY")
    print("=" * 70)
    for sector in sorted(sector_data.keys()):
        info = sector_data[sector]
        overall = info['overall_statistics']
        print(f"{sector:25s} | Avg Surprise: {overall['average_surprise_percent']:+6.2f}% | "
              f"Beat Rate: {overall['beat_rate']:5.1f}% | Companies: {overall['total_companies']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
