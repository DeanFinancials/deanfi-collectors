"""
Finnhub API Client for fetching market and company news.

This module provides functions to interact with Finnhub's news endpoints:
- Market News: Get latest general market news
- Company News: Get news for specific tickers with date ranges
"""
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.redact import redact_secrets  # noqa: E402


class FinnhubClient:
    """Client for interacting with Finnhub API."""
    
    def __init__(self, api_key: str, base_url: str = "https://finnhub.io/api/v1"):
        """
        Initialize Finnhub client.
        
        Args:
            api_key: Finnhub API key
            base_url: Base URL for Finnhub API (default: https://finnhub.io/api/v1)
        """
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.last_request_time = 0
        self.request_count = 0
        self.minute_start = time.time()
        self.max_calls_per_minute = 60  # Finnhub limit: 60 calls/minute
        
    def _rate_limit(self):
        """Implement rate limiting to stay under 60 API calls/minute."""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.minute_start >= 60:
            self.request_count = 0
            self.minute_start = current_time
        
        # If we've hit the limit, wait until the minute is up
        if self.request_count >= self.max_calls_per_minute:
            sleep_time = 60 - (current_time - self.minute_start)
            if sleep_time > 0:
                print(f"Rate limit: {self.request_count} calls in last minute. Waiting {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                self.request_count = 0
                self.minute_start = time.time()
        
        self.request_count += 1
        self.last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """
        Make API request with rate limiting and error handling.
        
        Args:
            endpoint: API endpoint (e.g., '/news')
            params: Query parameters
            
        Returns:
            JSON response as dict
        """
        self._rate_limit()
        
        if params is None:
            params = {}
        
        # Key in the header, not the URL, so it cannot leak via exception messages.
        headers = {'X-Finnhub-Token': self.api_key}
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                print(f"Rate limit exceeded. Waiting 1 second...", file=sys.stderr)
                time.sleep(1)
                return self._make_request(endpoint, params)  # Retry
            else:
                print(f"HTTP Error: {redact_secrets(e)}", file=sys.stderr)
                print(f"Response: {redact_secrets(response.text)}", file=sys.stderr)
                raise
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {redact_secrets(e)}", file=sys.stderr)
            raise
    
    def get_market_news(self, category: str = "general", min_id: int = 0) -> List[Dict]:
        """
        Get latest market news.
        
        Args:
            category: News category (general, forex, crypto, merger)
            min_id: Get only news after this ID (default: 0 for all)
            
        Returns:
            List of news articles
            
        Example response item:
            {
                "category": "technology",
                "datetime": 1596589501,  # UNIX timestamp
                "headline": "Square surges after...",
                "id": 5085164,
                "image": "https://...",
                "related": "",  # Related stocks
                "source": "CNBC",
                "summary": "Shares of Square...",
                "url": "https://www.cnbc.com/..."
            }
        """
        params = {
            'category': category,
            'minId': min_id
        }
        
        print(f"Fetching market news (category={category})...", file=sys.stderr)
        news = self._make_request('/news', params)
        print(f"✓ Retrieved {len(news)} market news articles", file=sys.stderr)
        return news
    
    def get_company_news(self, symbol: str, from_date: str, to_date: str) -> List[Dict]:
        """
        Get company news for a specific ticker.
        
        Args:
            symbol: Company ticker symbol (e.g., 'AAPL')
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            List of news articles for the company
            
        Example response item:
            {
                "category": "company news",
                "datetime": 1569550360,  # UNIX timestamp
                "headline": "Apple announces...",
                "id": 25286,
                "image": "https://...",
                "related": "AAPL",
                "source": "The Economic Times India",
                "summary": "Apple has announced...",
                "url": "https://..."
            }
        """
        params = {
            'symbol': symbol,
            'from': from_date,
            'to': to_date
        }
        
        try:
            news = self._make_request('/company-news', params)
            if news:
                print(f"  {symbol}: {len(news)} articles", file=sys.stderr)
            return news
        except Exception as e:
            print(f"  {symbol}: Error - {redact_secrets(e)}", file=sys.stderr)
            return []
    
    def get_company_news_batch(
        self, 
        symbols: List[str], 
        from_date: str, 
        to_date: str,
        verbose: bool = True
    ) -> Dict[str, List[Dict]]:
        """
        Get company news for multiple tickers.
        
        Args:
            symbols: List of ticker symbols
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            verbose: Print progress (default: True)
            
        Returns:
            Dict mapping ticker -> list of news articles
        """
        if verbose:
            print(f"\nFetching company news for {len(symbols)} tickers...", file=sys.stderr)
        
        results = {}
        for symbol in symbols:
            news = self.get_company_news(symbol, from_date, to_date)
            if news:  # Only include tickers with news
                results[symbol] = news
        
        if verbose:
            total_articles = sum(len(articles) for articles in results.values())
            print(f"✓ Retrieved {total_articles} total articles across {len(results)} tickers\n", file=sys.stderr)
        
        return results


def normalize_ticker(ticker: str) -> str:
    """
    Normalize ticker format for Finnhub API.
    
    Finnhub typically uses:
    - Dots become dashes: BRK.B -> BRK-B
    - Already has dashes: BRK-B -> BRK-B
    
    Args:
        ticker: Raw ticker symbol
        
    Returns:
        Normalized ticker
    """
    # Replace dots with dashes (BRK.B -> BRK-B)
    normalized = ticker.replace('.', '-')
    return normalized


def get_date_range(days_back: int = 2) -> tuple[str, str]:
    """
    Get date range for news query.
    
    Args:
        days_back: Number of days to look back (default: 2)
        
    Returns:
        Tuple of (from_date, to_date) in YYYY-MM-DD format
    """
    today = datetime.now()
    from_date = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date = today.strftime('%Y-%m-%d')
    
    return from_date, to_date


if __name__ == "__main__":
    # Quick test of the client
    import yaml
    
    # Load config
    with open('config.yml', 'r') as f:
        config = yaml.safe_load(f)
    
    # Initialize client
    client = FinnhubClient(config['api']['finnhub_api_key'])
    
    # Test market news
    print("Testing market news endpoint...")
    market_news = client.get_market_news(category='general')
    print(f"Got {len(market_news)} market news articles")
    
    if market_news:
        print("\nSample article:")
        article = market_news[0]
        print(f"  Headline: {article['headline']}")
        print(f"  Source: {article['source']}")
        print(f"  Time: {datetime.fromtimestamp(article['datetime'])}")
    
    # Test company news with one ticker
    from_date, to_date = get_date_range(days_back=2)
    print(f"\nTesting company news (XLK from {from_date} to {to_date})...")
    xlk_news = client.get_company_news('XLK', from_date, to_date)
    print(f"Got {len(xlk_news)} articles for XLK")
