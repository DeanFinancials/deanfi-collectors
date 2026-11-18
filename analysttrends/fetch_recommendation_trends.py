"""
Fetch Recommendation Trends Data for S&P 500 Companies

This script fetches analyst recommendation trends for all S&P 500 companies using the Finnhub API.
The data includes buy, hold, sell, strongBuy, and strongSell recommendations over time.

Output: recommendation_trends.json with detailed field descriptions and data for each ticker.

API Documentation: https://finnhub.io/docs/api/recommendation-trends
"""
import yaml
import json
import requests
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spx_universe import get_spx_tickers
from shared.redact import redact_secrets


class RecommendationTrendsFetcher:
    """Fetches recommendation trends data from Finnhub API."""
    
    def __init__(self, api_key: str, base_url: str = "https://finnhub.io/api/v1"):
        """
        Initialize the fetcher.
        
        Args:
            api_key: Finnhub API key
            base_url: Base URL for Finnhub API
        """
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.request_count = 0
        self.minute_start = time.time()
        self.max_calls_per_minute = 58  # Finnhub limit: 60/min, use 58 to be safe
        
    def _rate_limit(self):
        """Implement rate limiting to stay under API limits."""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.minute_start >= 60:
            self.request_count = 0
            self.minute_start = current_time
        
        # If approaching limit, wait until the minute is up
        if self.request_count >= self.max_calls_per_minute:
            sleep_time = 61 - (current_time - self.minute_start)  # Add 1s buffer
            if sleep_time > 0:
                print(f"⏳ Rate limit: Waiting {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                self.request_count = 0
                self.minute_start = time.time()
        
        # Small delay between requests to avoid bursts
        time.sleep(0.2)
    
    def fetch_recommendation_trends(self, symbol: str, debug: bool = False) -> Optional[List[Dict]]:
        """
        Fetch recommendation trends data for a symbol.
        
        Args:
            symbol: Stock ticker symbol
            debug: Print debug information
            
        Returns:
            List of recommendation trend dicts or None if error/no data
        """
        self._rate_limit()
        
        url = f"{self.base_url}/stock/recommendation"
        params = {"symbol": symbol}
        # Key in the header, not the URL, so it cannot leak via exception messages.
        headers = {"X-Finnhub-Token": self.api_key}
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=20)
            self.request_count += 1
            
            if debug:
                print(f"\n🔍 DEBUG {symbol}:", file=sys.stderr)
                print(f"  URL: {url}", file=sys.stderr)
                print(f"  Status: {response.status_code}", file=sys.stderr)
                print(f"  Headers: {dict(response.headers)}", file=sys.stderr)
                print(f"  Response length: {len(response.text)} chars", file=sys.stderr)
                print(f"  Response preview: {redact_secrets(response.text[:200])}", file=sys.stderr)
            
            # Handle rate limit before raising for status
            if response.status_code == 429:
                print(f"⚠️  Rate limit hit (429) for {symbol}. Waiting 60 seconds...", file=sys.stderr)
                time.sleep(60)
                self.request_count = 0
                self.minute_start = time.time()
                return self.fetch_recommendation_trends(symbol, debug)
            
            response.raise_for_status()
            data = response.json()
            
            # Check if we got valid data
            if not data or len(data) == 0:
                if debug:
                    print(f"  ⚠️  No data returned for {symbol}", file=sys.stderr)
                return None
            
            return data
            
        except requests.exceptions.Timeout:
            print(f"⚠️  Timeout for {symbol}", file=sys.stderr)
            return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching {symbol}: {redact_secrets(e)}", file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error for {symbol}: {e}", file=sys.stderr)
            return None


def load_config(config_path: Path) -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def main():
    """Main execution function."""
    # Setup paths
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yml"
    output_path = script_dir / "recommendation_trends.json"
    
    # Load config
    print("📋 Loading configuration...", file=sys.stderr)
    config = load_config(config_path)
    
    # Get API key from environment variable first, fallback to config
    import os
    api_key = os.getenv('FINNHUB_API_KEY')
    if not api_key:
        api_key = config['api'].get('finnhub_api_key')
    if not api_key:
        raise ValueError("FINNHUB_API_KEY environment variable not set. "
                        "Set it or add 'finnhub_api_key' to config.yml")
    ticker_exclusions = config['recommendation_trends'].get('ticker_exclusions', [])
    num_periods = config['recommendation_trends'].get('num_periods', 3)
    
    # Get S&P 500 tickers
    tickers = get_spx_tickers(exclusions=ticker_exclusions)
    print(f"📊 Processing {len(tickers)} S&P 500 tickers...\n", file=sys.stderr)
    
    # Initialize fetcher
    fetcher = RecommendationTrendsFetcher(api_key=api_key)
    
    # Fetch data for all tickers
    results = OrderedDict()
    total = len(tickers)
    success_count = 0
    no_data_count = 0
    error_count = 0
    
    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx}/{total}] Fetching {ticker}...", file=sys.stderr)
        
        data = fetcher.fetch_recommendation_trends(ticker, debug=False)
        
        if data is not None:
            # Keep only the latest N periods
            limited_data = data[:num_periods] if len(data) > num_periods else data
            results[ticker] = limited_data
            success_count += 1
            print(f"  ✅ Got {len(limited_data)} period(s) for {ticker}", file=sys.stderr)
        else:
            results[ticker] = {
                "note": "No recommendation data available for this ticker"
            }
            no_data_count += 1
            print(f"  ⚠️  No data for {ticker}", file=sys.stderr)
    
    # Compile final output
    output = OrderedDict()
    
    # Metadata
    output["metadata"] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "Finnhub Recommendation Trends API",
        "endpoint": "https://finnhub.io/docs/api/recommendation-trends",
        "num_periods_per_ticker": num_periods,
        "statistics": {
            "total_tickers": total,
            "tickers_with_data": success_count,
            "tickers_without_data": no_data_count,
            "errors": error_count
        }
    }
    
    # Field descriptions
    output["field_descriptions"] = {
        "symbol": "Stock ticker symbol",
        "period": "Period for the recommendation data (YYYY-MM-DD format, typically first of month)",
        "strongBuy": "Number of Strong Buy recommendations from analysts",
        "buy": "Number of Buy recommendations from analysts",
        "hold": "Number of Hold recommendations from analysts",
        "sell": "Number of Sell recommendations from analysts",
        "strongSell": "Number of Strong Sell recommendations from analysts",
        "total_recommendations": "Total number of analyst recommendations (calculated)",
        "bullish_ratio": "Percentage of bullish recommendations (strongBuy + buy) / total (calculated)",
        "interpretation": "Higher strongBuy and buy counts indicate positive analyst sentiment. Track changes over time to identify sentiment shifts."
    }
    
    # Add calculated metrics to each ticker's data
    for ticker, data in results.items():
        if isinstance(data, list):
            for period in data:
                # Calculate total recommendations
                total_recs = (
                    period.get('strongBuy', 0) + 
                    period.get('buy', 0) + 
                    period.get('hold', 0) + 
                    period.get('sell', 0) + 
                    period.get('strongSell', 0)
                )
                period['total_recommendations'] = total_recs
                
                # Calculate bullish ratio
                if total_recs > 0:
                    bullish = period.get('strongBuy', 0) + period.get('buy', 0)
                    period['bullish_ratio'] = round((bullish / total_recs) * 100, 2)
                else:
                    period['bullish_ratio'] = 0.0
    
    # Data
    output["data"] = results
    
    # Write to file
    print(f"\n💾 Writing results to {output_path}...", file=sys.stderr)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✅ Complete!", file=sys.stderr)
    print(f"📊 Results:", file=sys.stderr)
    print(f"   - Total tickers: {total}", file=sys.stderr)
    print(f"   - With data: {success_count}", file=sys.stderr)
    print(f"   - Without data: {no_data_count}", file=sys.stderr)
    print(f"   - Errors: {error_count}", file=sys.stderr)
    print(f"\n📁 Output: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
