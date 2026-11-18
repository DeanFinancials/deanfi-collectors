#!/usr/bin/env python3
"""
Earnings Surprises Data Fetcher
================================
Fetches quarterly earnings surprise data for S&P 500 companies from Finnhub API.

API Endpoint: /stock/earnings
Free Tier: Last 4 quarters of historical data
Rate Limit: 60 calls/minute

Data Fields:
- actual: Actual EPS reported
- estimate: Analyst consensus estimate
- period: Report date (YYYY-MM-DD)
- quarter: Fiscal quarter (1-4)
- surprise: Difference between actual and estimate
- surprisePercent: Percentage surprise
- symbol: Stock ticker
- year: Fiscal year

Output: earnings_surprises.json with last 4 quarters for each S&P 500 ticker
"""

import requests
import yaml
import json
import time
from pathlib import Path
from datetime import datetime
from collections import deque

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spx_universe import get_spx_tickers
from shared.redact import redact_secrets


class EarningsSurprisesFetcher:
    """Fetches earnings surprise data from Finnhub API with rate limiting."""
    
    def __init__(self, config_path="config.yml"):
        """Initialize fetcher with configuration."""
        import os
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Get API key from environment variable first, fallback to config
        self.api_key = os.getenv('FINNHUB_API_KEY')
        if not self.api_key:
            self.api_key = self.config['api'].get('key')
        if not self.api_key:
            raise ValueError("FINNHUB_API_KEY environment variable not set")
        self.base_url = self.config['api']['base_url']
        self.endpoint = self.config['api']['endpoint']
        self.quarters_limit = self.config['data']['quarters_to_fetch']
        
        # Rate limiting configuration
        self.calls_per_minute = self.config['rate_limiting']['calls_per_minute']
        self.delay = self.config['rate_limiting']['delay_between_calls']
        self.window_size = self.config['rate_limiting']['window_size']
        
        # Track API calls for rate limiting
        self.call_times = deque(maxlen=self.calls_per_minute)
        
        # Stats tracking
        self.stats = {
            'total_tickers': 0,
            'successful': 0,
            'failed': 0,
            'no_data': 0,
            'api_calls': 0
        }
    
    def _rate_limit(self):
        """Enforce rate limiting using sliding window."""
        now = time.time()
        
        # Remove calls outside the current window
        while self.call_times and self.call_times[0] < now - self.window_size:
            self.call_times.popleft()
        
        # If we've hit the limit, wait
        if len(self.call_times) >= self.calls_per_minute:
            sleep_time = self.window_size - (now - self.call_times[0]) + 0.1
            if sleep_time > 0:
                print(f"Rate limit reached. Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                now = time.time()
        
        # Add fixed delay between calls
        time.sleep(self.delay)
        
        # Record this call
        self.call_times.append(now)
        self.stats['api_calls'] += 1
    
    def fetch_ticker_earnings(self, symbol):
        """
        Fetch earnings surprise data for a single ticker.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            List of earnings data (up to 4 quarters), or None if error/no data
        """
        self._rate_limit()
        
        url = f"{self.base_url}{self.endpoint}"
        params = {
            'symbol': symbol,
            'limit': self.quarters_limit,
        }
        # Key in the header, not the URL, so it cannot leak via exception messages.
        headers = {'X-Finnhub-Token': self.api_key}
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # API returns empty list if no data available
            if not data or len(data) == 0:
                print(f"  ⚠ {symbol}: No earnings data available")
                self.stats['no_data'] += 1
                return None
            
            # Validate data structure
            for quarter_data in data:
                if not all(key in quarter_data for key in ['actual', 'estimate', 'period', 'quarter', 'year']):
                    print(f"  ⚠ {symbol}: Incomplete data structure")
                    return None
            
            print(f"  ✓ {symbol}: {len(data)} quarters retrieved")
            self.stats['successful'] += 1
            return data
            
        except requests.exceptions.RequestException as e:
            print(f"  ✗ {symbol}: API error - {redact_secrets(e)}")
            self.stats['failed'] += 1
            return None
        except json.JSONDecodeError:
            print(f"  ✗ {symbol}: Invalid JSON response")
            self.stats['failed'] += 1
            return None
    
    def fetch_all_earnings(self):
        """
        Fetch earnings surprise data for all S&P 500 tickers.
        
        Returns:
            Dictionary mapping ticker symbols to their earnings data
        """
        print("=" * 70)
        print("FETCHING EARNINGS SURPRISES DATA")
        print("=" * 70)
        
        # Get S&P 500 tickers and exclude duplicates
        tickers = get_spx_tickers()
        exclude_list = self.config['data']['exclude_tickers']
        tickers = [t for t in tickers if t not in exclude_list]
        
        self.stats['total_tickers'] = len(tickers)
        
        print(f"\nFetching earnings data for {len(tickers)} S&P 500 companies")
        print(f"Rate limit: {self.calls_per_minute} calls/minute")
        print(f"Quarters per ticker: {self.quarters_limit}")
        print(f"Estimated time: ~{(len(tickers) * self.delay / 60):.1f} minutes\n")
        
        earnings_data = {}
        
        for i, ticker in enumerate(tickers, 1):
            print(f"[{i}/{len(tickers)}] {ticker}")
            
            data = self.fetch_ticker_earnings(ticker)
            if data is not None:
                earnings_data[ticker] = data
        
        return earnings_data
    
    def save_to_json(self, data, output_file):
        """Save earnings data to JSON file with metadata."""
        output_path = Path(output_file)
        
        # Prepare output with metadata
        output = {
            "metadata": {
                "data_source": "Finnhub Earnings Surprises API",
                "api_endpoint": f"{self.base_url}{self.endpoint}",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_tickers": len(data),
                "quarters_per_ticker": self.quarters_limit,
                "data_description": "Quarterly earnings surprises for S&P 500 companies"
            },
            "field_descriptions": {
                "actual": "Actual EPS reported by the company",
                "estimate": "Analyst consensus EPS estimate",
                "period": "Earnings report date (YYYY-MM-DD)",
                "quarter": "Fiscal quarter (1-4)",
                "surprise": "Difference between actual and estimate (actual - estimate)",
                "surprisePercent": "Percentage surprise ((actual - estimate) / |estimate| * 100)",
                "symbol": "Stock ticker symbol",
                "year": "Fiscal year"
            },
            "data": data
        }
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        # Get file size
        file_size = output_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        print(f"\n✓ Data saved to {output_file}")
        print(f"  File size: {file_size_mb:.2f} MB ({file_size:,} bytes)")
    
    def print_summary(self):
        """Print execution summary statistics."""
        print("\n" + "=" * 70)
        print("FETCH SUMMARY")
        print("=" * 70)
        print(f"Total tickers processed: {self.stats['total_tickers']}")
        print(f"Successful: {self.stats['successful']} ({self.stats['successful']/self.stats['total_tickers']*100:.1f}%)")
        print(f"No data: {self.stats['no_data']}")
        print(f"Failed: {self.stats['failed']}")
        print(f"API calls made: {self.stats['api_calls']}")
        print("=" * 70)


def main():
    """Main execution function."""
    start_time = time.time()
    
    # Initialize fetcher
    fetcher = EarningsSurprisesFetcher()
    
    # Fetch all earnings data
    earnings_data = fetcher.fetch_all_earnings()
    
    # Save to JSON
    output_file = fetcher.config['output']['raw_data']
    fetcher.save_to_json(earnings_data, output_file)
    
    # Print summary
    fetcher.print_summary()
    
    # Print execution time
    elapsed = time.time() - start_time
    print(f"\nTotal execution time: {elapsed/60:.2f} minutes ({elapsed:.1f} seconds)")


if __name__ == "__main__":
    main()
