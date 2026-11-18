#!/usr/bin/env python3
"""
Fetch Earnings Calendar Data

Retrieves historical and upcoming earnings release dates with EPS and Revenue
data for all S&P 500 companies using the Finnhub Earnings Calendar API.

Output: earnings_calendar.json with comprehensive earnings calendar data
"""

import json
import time
import yaml
import requests
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Optional, Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spx_universe import get_spx_tickers
from shared.redact import redact_secrets


class EarningsCalendarFetcher:
    """Fetches earnings calendar data for S&P 500 companies with rate limiting."""
    
    def __init__(self, config_path: str = "config.yml"):
        """Initialize with configuration."""
        import os
        self.config = self._load_config(config_path)
        
        # Get API key from environment variable first, fallback to config
        self.api_key = os.getenv('FINNHUB_API_KEY')
        if not self.api_key:
            self.api_key = self.config['api'].get('key')
        if not self.api_key:
            raise ValueError("FINNHUB_API_KEY environment variable not set")
        self.base_url = self.config['api']['base_url']
        self.calls_per_minute = self.config['rate_limiting']['calls_per_minute']
        self.delay_between_calls = self.config['rate_limiting']['delay_between_calls']
        self.window_size = self.config['rate_limiting']['sliding_window_size']
        
        # Sliding window for rate limiting
        self.call_times = deque(maxlen=self.calls_per_minute)
        
        # Statistics
        self.stats = {
            'total_tickers': 0,
            'successful': 0,
            'no_data': 0,
            'failed': 0,
            'total_earnings_events': 0,
            'api_calls': 0
        }
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _get_date_range(self) -> tuple[str, str]:
        """Calculate date range based on configuration."""
        config_dates = self.config['date_range']
        
        # Check if exact dates are specified
        if config_dates.get('from_date') and config_dates.get('to_date'):
            return config_dates['from_date'], config_dates['to_date']
        
        # Otherwise calculate from historical_days and future_days
        today = datetime.now()
        from_date = today - timedelta(days=config_dates['historical_days'])
        to_date = today + timedelta(days=config_dates['future_days'])
        
        return from_date.strftime('%Y-%m-%d'), to_date.strftime('%Y-%m-%d')
    
    def _rate_limit(self):
        """Implement sliding window rate limiting."""
        current_time = time.time()
        
        # Remove calls outside the sliding window
        while self.call_times and (current_time - self.call_times[0]) > self.window_size:
            self.call_times.popleft()
        
        # If we've hit the limit, wait
        if len(self.call_times) >= self.calls_per_minute:
            sleep_time = self.window_size - (current_time - self.call_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.call_times.popleft()
        
        # Add delay between calls
        time.sleep(self.delay_between_calls)
        
        # Record this call
        self.call_times.append(time.time())
    
    def fetch_earnings_calendar(self, symbol: str, from_date: str, to_date: str) -> Optional[List[Dict]]:
        """
        Fetch earnings calendar data for a single symbol.
        
        Args:
            symbol: Stock ticker symbol
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            
        Returns:
            List of earnings events or None if error/no data
        """
        self._rate_limit()
        
        url = f"{self.base_url}/calendar/earnings"
        params = {
            'from': from_date,
            'to': to_date,
            'symbol': symbol,
        }
        # Key in the header, not the URL, so it cannot leak via exception messages.
        headers = {'X-Finnhub-Token': self.api_key}
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                earnings_calendar = data.get('earningsCalendar', [])
                
                if earnings_calendar:
                    self.stats['successful'] += 1
                    self.stats['total_earnings_events'] += len(earnings_calendar)
                    return earnings_calendar
                else:
                    self.stats['no_data'] += 1
                    return []
            else:
                print(f"  ✗ {symbol}: HTTP {response.status_code}")
                self.stats['failed'] += 1
                return None
                
        except Exception as e:
            print(f"  ✗ {symbol}: API error - {redact_secrets(e)}")
            self.stats['failed'] += 1
            return None
    
    def fetch_all_earnings(self) -> Dict[str, Any]:
        """
        Fetch earnings calendar data for all S&P 500 companies.
        
        Returns:
            Dictionary with all earnings calendar data and metadata
        """
        print("="*70)
        print("FETCHING EARNINGS CALENDAR DATA")
        print("="*70)
        
        # Get S&P 500 tickers
        tickers = get_spx_tickers()
        self.stats['total_tickers'] = len(tickers)
        
        # Get date range
        from_date, to_date = self._get_date_range()
        
        print(f"\n📅 Date Range: {from_date} to {to_date}")
        print(f"📊 Fetching earnings calendar for {len(tickers)} S&P 500 companies")
        print(f"⏱️  Rate limit: {self.calls_per_minute} calls/minute")
        
        # Estimate time
        estimated_minutes = len(tickers) / self.calls_per_minute
        print(f"⏱️  Estimated time: ~{estimated_minutes:.1f} minutes\n")
        
        # Fetch data for each ticker
        all_earnings = []
        
        for i, ticker in enumerate(tickers, 1):
            print(f"[{i}/{len(tickers)}] {ticker}")
            
            earnings_data = self.fetch_earnings_calendar(ticker, from_date, to_date)
            
            if earnings_data is not None:
                if earnings_data:
                    print(f"  ✓ {ticker}: {len(earnings_data)} earnings event(s) found")
                    all_earnings.extend(earnings_data)
                else:
                    print(f"  ⚠ {ticker}: No earnings data in date range")
            # Error message already printed in fetch_earnings_calendar
        
        # Sort by date (most recent first)
        all_earnings.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        # Build output structure
        output = {
            '_README': self._generate_readme(),
            'metadata': {
                'data_source': 'Finnhub Earnings Calendar API',
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date_range': {
                    'from': from_date,
                    'to': to_date
                },
                'total_tickers_queried': self.stats['total_tickers'],
                'tickers_with_data': self.stats['successful'],
                'total_earnings_events': self.stats['total_earnings_events'],
                'api_calls_made': self.stats['api_calls']
            },
            'timing_legend': {
                'bmo': 'Before Market Open',
                'amc': 'After Market Close',
                'dmh': 'During Market Hours'
            },
            'earnings_calendar': all_earnings
        }
        
        return output
    
    def _generate_readme(self) -> Dict[str, Any]:
        """Generate comprehensive README section for JSON output."""
        return {
            'description': 'Historical and upcoming earnings release dates with EPS and Revenue data for S&P 500 companies',
            'purpose': 'Track earnings announcements, compare actual vs estimated results, plan for market-moving events',
            'data_source': 'Finnhub Earnings Calendar API (non-GAAP EPS and Revenue)',
            'free_tier_limitation': '1 month of historical earnings and new updates',
            'field_descriptions': {
                'date': 'Earnings release date (YYYY-MM-DD)',
                'symbol': 'Stock ticker symbol',
                'epsActual': 'Actual non-GAAP earnings per share (null if not yet reported)',
                'epsEstimate': 'Estimated earnings per share from analyst consensus',
                'revenueActual': 'Actual revenue in dollars (null if not yet reported)',
                'revenueEstimate': "Revenue estimate including Finnhub's proprietary estimates",
                'hour': 'Timing of announcement: bmo (before market open), amc (after market close), dmh (during market hours)',
                'quarter': 'Fiscal quarter (1, 2, 3, or 4)',
                'year': 'Fiscal year'
            },
            'usage_examples': {
                'upcoming_earnings': 'Filter by date >= today to see upcoming earnings announcements',
                'surprise_analysis': 'Compare epsActual vs epsEstimate to calculate earnings surprises',
                'revenue_trends': 'Track revenueActual vs revenueEstimate across quarters',
                'timing_patterns': 'Group by hour to see which companies report bmo vs amc',
                'calendar_planning': 'Use date field to plan trading around earnings events'
            },
            'update_frequency': 'Daily recommended to capture new earnings announcements and updated estimates',
            'sorting': 'Events sorted by date (most recent first)',
            'note_on_nulls': 'epsActual and revenueActual are null for future earnings (not yet reported)'
        }
    
    def save_to_json(self, data: Dict, output_file: str):
        """Save data to JSON file."""
        output_path = Path(output_file)
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        file_size = output_path.stat().st_size
        print(f"\n✓ Data saved to {output_file}")
        print(f"  File size: {file_size / 1024 / 1024:.2f} MB ({file_size:,} bytes)")
    
    def print_summary(self):
        """Print fetch summary statistics."""
        print("\n" + "="*70)
        print("FETCH SUMMARY")
        print("="*70)
        print(f"Total tickers queried: {self.stats['total_tickers']}")
        print(f"Tickers with earnings data: {self.stats['successful']} ({self.stats['successful']/self.stats['total_tickers']*100:.1f}%)")
        print(f"Tickers with no data: {self.stats['no_data']}")
        print(f"Failed: {self.stats['failed']}")
        print(f"Total earnings events: {self.stats['total_earnings_events']}")
        print(f"API calls made: {self.stats['api_calls']}")
        print("="*70)


def main():
    """Main execution function."""
    start_time = time.time()
    
    # Initialize fetcher
    fetcher = EarningsCalendarFetcher()
    
    # Fetch all earnings calendar data
    earnings_data = fetcher.fetch_all_earnings()
    
    # Save to JSON
    output_file = fetcher.config['output']['earnings_calendar_file']
    fetcher.save_to_json(earnings_data, output_file)
    
    # Print summary
    fetcher.print_summary()
    
    # Print execution time
    elapsed = time.time() - start_time
    print(f"\nTotal execution time: {elapsed/60:.2f} minutes ({elapsed:.1f} seconds)")


if __name__ == '__main__':
    main()
