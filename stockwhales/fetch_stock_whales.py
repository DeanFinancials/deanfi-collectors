#!/usr/bin/env python3
"""
Stock Whale Collector

Fetches large stock trades ("whale trades") for S&P 500 constituents
using the Alpaca Markets Stock Trades API.

Focuses on identifying institutional activity, particularly dark pool trades.

Outputs:
- stock_whale_summary.json: Aggregate summary data with sector breakdowns
- stock_whale_trades.json: Per-ticker whale trades with detailed info

Environment Variables Required:
- ALPACA_API_KEY: Alpaca API Key ID (or APCA-API-KEY-ID)
- ALPACA_API_SECRET: Alpaca API Secret Key (or APCA-API-SECRET-KEY)

Usage:
    python fetch_stock_whales.py                    # Full S&P 500 scan
    python fetch_stock_whales.py --test             # Test with 5 tickers
    python fetch_stock_whales.py --tickers AAPL,MSFT,NVDA  # Custom tickers
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict

import requests
import yaml

# Add parent directory to path for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.spx_universe import get_spx_tickers
from shared.sector_mapping import get_sector
from shared.ticker_metadata import get_industry, get_sub_industry
from shared.ticker_utils import dedupe_company_tickers

from utils import (
    get_lookback_start_date,
    get_trading_day_count,
    convert_ticker_for_alpaca,
    convert_ticker_from_alpaca,
    infer_trade_direction,
    find_optimal_threshold,
    get_ticker_multiplier,
    classify_trade_tier,
    calculate_sentiment,
    calculate_dark_pool_sentiment,
    calculate_sector_sentiment,
    format_currency,
    format_shares,
    safe_round,
    RateLimiter,
)


# =============================================================================
# CONFIGURATION LOADING
# =============================================================================

def load_config() -> Dict:
    """Load configuration from config.yml"""
    config_path = Path(__file__).parent / "config.yml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


# =============================================================================
# ALPACA API CLIENT
# =============================================================================

class AlpacaStockClient:
    """Client for Alpaca Markets Stock Trades API."""
    
    BASE_URL = "https://data.alpaca.markets"
    
    def __init__(self, api_key: str, api_secret: str, rate_limiter: RateLimiter):
        """
        Initialize Alpaca client.
        
        Args:
            api_key: Alpaca API Key ID
            api_secret: Alpaca API Secret Key
            rate_limiter: RateLimiter instance for rate limiting
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.rate_limiter = rate_limiter
        self.headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': api_secret
        }
    
    def _request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Make a rate-limited API request.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            Response JSON or None on error
        """
        self.rate_limiter.wait_if_needed()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate limited - wait and retry
                print(f"Rate limited, waiting 5s...")
                time.sleep(5)
                return self._request(endpoint, params)
            else:
                print(f"API error {response.status_code}: {response.text[:200]}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return None
    
    def get_stock_trades(self, symbol: str, start_date: datetime, 
                         end_date: datetime = None, limit: int = 10000) -> List[Dict]:
        """
        Fetch historical trades for a stock.
        
        Args:
            symbol: Stock ticker symbol
            start_date: Start of time range
            end_date: End of time range (default: now)
            limit: Maximum trades to return
            
        Returns:
            List of trade dictionaries
        """
        endpoint = f"/v2/stocks/{symbol}/trades"
        params = {
            'start': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'limit': limit,
            'sort': 'desc'
        }
        
        if end_date:
            params['end'] = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        response = self._request(endpoint, params)
        return response.get('trades', []) if response else []
    
    def get_stock_quotes(self, symbol: str, start_date: datetime,
                         end_date: datetime = None, limit: int = 10000) -> List[Dict]:
        """
        Fetch historical quotes for direction inference.
        
        Args:
            symbol: Stock ticker symbol
            start_date: Start of time range
            end_date: End of time range (default: now)
            limit: Maximum quotes to return
            
        Returns:
            List of quote dictionaries
        """
        endpoint = f"/v2/stocks/{symbol}/quotes"
        params = {
            'start': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'limit': limit,
            'sort': 'asc'  # Ascending for efficient quote lookup
        }
        
        if end_date:
            params['end'] = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        response = self._request(endpoint, params)
        return response.get('quotes', []) if response else []
    
    def get_latest_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get the latest quote for a stock.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Quote dictionary or None
        """
        endpoint = f"/v2/stocks/{symbol}/quotes/latest"
        response = self._request(endpoint)
        return response.get('quote') if response else None


# =============================================================================
# TRADE PROCESSING
# =============================================================================

def find_closest_quote(trade_timestamp: str, quotes: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """
    Find the closest quote before the trade timestamp.
    
    Args:
        trade_timestamp: ISO timestamp of the trade
        quotes: List of quote dictionaries sorted ascending by timestamp
        
    Returns:
        Tuple of (bid_price, ask_price) or (None, None)
    """
    if not quotes:
        return None, None
    
    # Parse trade timestamp
    if isinstance(trade_timestamp, str):
        # Handle ISO format with Z or timezone
        trade_time = trade_timestamp.replace('Z', '+00:00')
    else:
        trade_time = trade_timestamp
    
    closest_quote = None
    
    for quote in quotes:
        quote_time = quote.get('t', '')
        if isinstance(quote_time, str):
            quote_time = quote_time.replace('Z', '+00:00')
        
        # Simple string comparison works for ISO timestamps
        if quote_time <= trade_time:
            closest_quote = quote
        else:
            break
    
    if closest_quote:
        return closest_quote.get('bp'), closest_quote.get('ap')
    
    return None, None


def process_trades_for_ticker(client: AlpacaStockClient, ticker: str,
                              start_date: datetime, config: Dict) -> Tuple[List[Dict], int]:
    """
    Process all trades for a single ticker.
    
    Fetches trades and quotes, applies whale threshold, infers direction.
    
    Args:
        client: AlpacaStockClient instance
        ticker: Stock ticker symbol
        start_date: Start of lookback period
        config: Configuration dictionary
        
    Returns:
        Tuple of (whale_trades, raw_trade_count)
    """
    # Convert ticker for Alpaca API
    alpaca_ticker = convert_ticker_for_alpaca(ticker)
    if alpaca_ticker is None:
        return [], 0
    
    # Get thresholds from config
    min_shares = config['thresholds']['minimum_shares']
    min_value = config['thresholds']['minimum_value']
    direction_config = config.get('direction', {})
    near_ask = direction_config.get('near_ask_threshold', 0.7)
    near_bid = direction_config.get('near_bid_threshold', 0.3)
    
    # Fetch trades
    trades = client.get_stock_trades(
        alpaca_ticker, 
        start_date,
        limit=config['collection'].get('fetch_limit', 10000)
    )
    
    if not trades:
        return [], 0
    
    raw_trade_count = len(trades)
    
    # First pass: filter to potential whale trades (loose filter)
    # We use the minimum threshold to get candidates
    potential_whales = []
    for trade in trades:
        size = trade.get('s', 0)
        price = trade.get('p', 0)
        value = size * price
        
        if size >= min_shares or value >= min_value:
            potential_whales.append({
                'raw_trade': trade,
                'shares': size,
                'price': price,
                'value': value
            })
    
    if not potential_whales:
        return [], raw_trade_count
    
    # Fetch quotes for direction inference
    quotes = client.get_stock_quotes(
        alpaca_ticker,
        start_date,
        limit=config['collection'].get('fetch_limit', 10000)
    )
    
    # Process each potential whale trade
    whale_trades = []
    for pw in potential_whales:
        trade = pw['raw_trade']
        
        # Get quote data for direction inference
        bid, ask = find_closest_quote(trade.get('t', ''), quotes)
        direction_info = infer_trade_direction(
            pw['price'], bid, ask, near_ask, near_bid
        )
        
        # Determine if dark pool
        exchange = trade.get('x', '')
        is_dark_pool = exchange == 'D'
        
        # Build trade record
        trade_record = {
            'ticker': ticker,  # Use original ticker format
            'timestamp': trade.get('t', ''),
            'price': pw['price'],
            'shares': pw['shares'],
            'value': pw['value'],
            'exchange': exchange,
            'is_dark_pool': is_dark_pool,
            'tape': trade.get('z', ''),
            'direction': direction_info['direction'],
            'direction_confidence': direction_info['confidence'],
            'direction_emoji': direction_info['emoji'],
            'direction_desc': direction_info['description'],
            # Tier will be added after threshold filtering
        }
        
        whale_trades.append(trade_record)
    
    return whale_trades, raw_trade_count


def apply_dynamic_threshold(trades: List[Dict], ticker: str, config: Dict) -> Tuple[Dict, List[Dict]]:
    """
    Apply dynamic threshold to a ticker's trades.
    
    Args:
        trades: List of trade dictionaries
        ticker: Stock ticker symbol
        config: Configuration dictionary
        
    Returns:
        Tuple of (effective_tier, filtered_trades)
    """
    # Get ticker multiplier
    classifications = config.get('ticker_size', {}).get('classifications', {})
    multipliers = config.get('ticker_size', {}).get('multipliers', {'mid': 1.0})
    multiplier = get_ticker_multiplier(ticker, classifications, multipliers)
    
    # Apply dynamic threshold
    tier, filtered = find_optimal_threshold(
        trades,
        config['thresholds']['tiers'],
        config['thresholds']['target_min'],
        config['thresholds']['target_max'],
        config['thresholds']['hard_max'],
        multiplier
    )
    
    # Add tier classification to each trade
    tier_labels = config.get('tier_labels', {})
    for trade in filtered:
        tier_info = classify_trade_tier(trade['value'], tier_labels)
        trade['tier'] = tier_info['tier']
        trade['tier_label'] = tier_info['label']
        trade['tier_emoji'] = tier_info['emoji']
    
    return tier, filtered


# =============================================================================
# JSON OUTPUT GENERATION
# =============================================================================

def generate_readme_section(config: Dict) -> Dict:
    """Generate the _README section for JSON outputs."""
    return {
        "title": "S&P 500 Stock Whale Trades",
        "description": "Large stock trades detected over 5 trading days for S&P 500 constituents",
        "purpose": "Identify institutional-sized stock trades for sentiment analysis, particularly dark pool activity",
        "data_source": "Alpaca Markets Stock Trades API",
        "methodology": {
            "lookback_days": config['collection']['lookback_trading_days'],
            "lookback_type": "Trading days (excludes weekends and NYSE holidays)",
            "threshold_approach": "Dynamic - starts at 5K shares/$1M minimum, steps up until <= 10 trades per ticker",
            "threshold_logic": "Trade qualifies if shares >= threshold OR value >= threshold (OR logic)",
            "direction_inference": "Lee-Ready algorithm - compares trade price to bid/ask spread",
            "dark_pool_indicator": "Exchange code 'D' = FINRA ADF / Off-Exchange (institutional)",
            "max_trades_per_ticker": config['thresholds']['hard_max']
        },
        "field_descriptions": {
            "ticker": "Stock ticker symbol",
            "shares": "Number of shares in the trade",
            "value": "Dollar value of the trade (price × shares)",
            "is_dark_pool": "True if trade executed on dark pool (Exchange D)",
            "exchange": "Exchange code where trade occurred",
            "tape": "Tape indicator (A=NYSE, B=NYSE Arca/regional, C=NASDAQ)",
            "direction": "Inferred trade direction (BUY/SELL/NEUTRAL)",
            "direction_confidence": "Confidence percentage (0-95%) of direction inference",
            "tier": "Size classification (notable/large/whale/mega_whale)",
            "effective_threshold": "The dynamic threshold applied to this ticker"
        },
        "direction_interpretation": {
            "BUY": "Trade executed at/above ask - aggressive buyer lifted offer",
            "SELL": "Trade executed at/below bid - aggressive seller hit bid",
            "NEUTRAL": "Trade at midpoint - direction unclear",
            "buy_sell_ratio": "Ratio > 1 = bullish bias, < 1 = bearish bias"
        },
        "dark_pool_context": config['interpretation']['dark_pool_context'],
        "tier_descriptions": config['interpretation']['tier_descriptions'],
        "update_schedule": "Daily at Noon ET (mid-market) and 9 PM ET (post-market)"
    }


def _build_top_trades_by_ticker(trades: List[Dict], direction_filter: str, max_tickers: int = 10) -> List[Dict]:
    """
    Build a top trades list with one entry per ticker.
    
    Args:
        trades: List of trade dictionaries
        direction_filter: 'BUY' or 'SELL' to filter by direction
        max_tickers: Maximum number of tickers to include
        
    Returns:
        List of trade summaries, one per ticker
    """
    # Filter by direction
    filtered = [t for t in trades if t.get('direction') == direction_filter]
    
    if not filtered:
        return []
    
    # Group by ticker
    trades_by_ticker = defaultdict(list)
    for t in filtered:
        ticker = t.get('ticker')
        if ticker:
            trades_by_ticker[ticker].append(t)
    
    # Sort trades within each ticker by value (highest first)
    for ticker in trades_by_ticker:
        trades_by_ticker[ticker].sort(key=lambda x: x.get('value', 0), reverse=True)
    
    # Get the highest trade for each ticker
    ticker_max_trades = []
    for ticker, ticker_trades in trades_by_ticker.items():
        if ticker_trades:
            ticker_max_trades.append({
                'ticker': ticker,
                'max_trade': ticker_trades[0],
                'max_value': ticker_trades[0].get('value', 0),
                'all_trades': ticker_trades,
                'trade_count': len(ticker_trades)
            })
    
    # Sort by max value descending
    ticker_max_trades.sort(key=lambda x: x['max_value'], reverse=True)
    
    # Take top N tickers
    top_tickers = ticker_max_trades[:max_tickers]
    
    # Build result
    result = []
    for entry in top_tickers:
        ticker = entry['ticker']
        max_trade = entry['max_trade']
        all_trades = entry['all_trades']
        
        # Count dark pool trades
        dark_pool_trades = [t for t in all_trades if t.get('is_dark_pool')]
        dark_pool_value = sum(t.get('value', 0) for t in dark_pool_trades)
        
        result.append({
            "ticker": ticker,
            "value": max_trade.get('value'),
            "shares": max_trade.get('shares'),
            "price": max_trade.get('price'),
            "timestamp": max_trade.get('timestamp'),
            "is_dark_pool": max_trade.get('is_dark_pool'),
            "tier": max_trade.get('tier_label', max_trade.get('tier')),
            "direction_confidence": max_trade.get('direction_confidence'),
            "sector": get_sector(ticker),
            "industry": get_industry(ticker),
            "sub_industry": get_sub_industry(ticker),
            "total_trades": entry['trade_count'],
            "dark_pool_count": len(dark_pool_trades),
            "dark_pool_value": dark_pool_value,
            "total_ticker_value": sum(t.get('value', 0) for t in all_trades)
        })
    
    return result


def build_summary_json(all_trades: Dict[str, List[Dict]], 
                       metadata: Dict, config: Dict) -> Dict:
    """
    Build the summary JSON output.
    
    Args:
        all_trades: Dictionary mapping ticker to list of whale trades
        metadata: Collection metadata
        config: Configuration dictionary
        
    Returns:
        Summary JSON dictionary
    """
    # Flatten all trades
    flat_trades = []
    for ticker_trades in all_trades.values():
        flat_trades.extend(ticker_trades)
    
    if not flat_trades:
        return {
            "_README": generate_readme_section(config),
            "metadata": metadata,
            "overall_sentiment": {"direction": "NEUTRAL", "message": "No whale trades found"},
            "dark_pool_sentiment": {"direction": "NEUTRAL", "message": "No dark pool trades found"},
            "sector_sentiment": {},
            "top_bullish_trades": {"trades": []},
            "top_bearish_trades": {"trades": []},
            "tier_breakdown": {},
            "exchange_breakdown": {}
        }
    
    high_conf_threshold = config.get('direction', {}).get('high_confidence_threshold', 80)
    
    # Calculate overall sentiment
    overall_sentiment = calculate_sentiment(flat_trades, high_conf_threshold)
    
    # Separate dark pool trades
    dark_pool_trades = [t for t in flat_trades if t.get('is_dark_pool')]
    lit_trades = [t for t in flat_trades if not t.get('is_dark_pool')]
    
    # Dark pool sentiment
    dark_pool_sentiment = calculate_dark_pool_sentiment(dark_pool_trades, high_conf_threshold)
    
    # Lit exchange sentiment
    lit_sentiment = calculate_sentiment(lit_trades, high_conf_threshold)
    
    # Sector sentiment
    trades_by_ticker = {ticker: trades for ticker, trades in all_trades.items()}
    sector_sentiment = calculate_sector_sentiment(trades_by_ticker, None, high_conf_threshold)
    
    # Sort sectors by total value
    sorted_sectors = sorted(
        sector_sentiment.items(),
        key=lambda x: x[1]['buy_value'] + x[1]['sell_value'],
        reverse=True
    )
    
    # Build sector details
    sector_details = {}
    for sector, sentiment in sorted_sectors:
        if sentiment['trade_count'] > 0:
            sector_details[sector] = {
                "sentiment": sentiment['direction'],
                "high_confidence_sentiment": sentiment['high_confidence_direction'],
                "buy_value": sentiment['buy_value'],
                "sell_value": sentiment['sell_value'],
                "net_value": sentiment['net_value'],
                "buy_sell_ratio": sentiment['buy_sell_ratio'],
                "buy_count": sentiment['buy_count'],
                "sell_count": sentiment['sell_count'],
                "trade_count": sentiment['trade_count'],
                "ticker_count": sentiment['ticker_count']
            }
    
    # Tier breakdown
    tier_counts = defaultdict(lambda: {'count': 0, 'value': 0, 'dark_pool_count': 0})
    for trade in flat_trades:
        tier = trade.get('tier', 'unknown')
        tier_counts[tier]['count'] += 1
        tier_counts[tier]['value'] += trade.get('value', 0)
        if trade.get('is_dark_pool'):
            tier_counts[tier]['dark_pool_count'] += 1
    
    # Exchange breakdown
    exchange_counts = defaultdict(lambda: {'count': 0, 'value': 0})
    exchange_names = config.get('exchange_names', {})
    for trade in flat_trades:
        exchange = trade.get('exchange', 'Unknown')
        exchange_counts[exchange]['count'] += 1
        exchange_counts[exchange]['value'] += trade.get('value', 0)
    
    # Add exchange names
    exchange_breakdown = {}
    for exchange, data in sorted(exchange_counts.items(), key=lambda x: x[1]['value'], reverse=True):
        exchange_breakdown[exchange] = {
            **data,
            'name': exchange_names.get(exchange, exchange),
            'is_dark_pool': exchange == 'D'
        }
    
    # Top bullish trades (one per ticker)
    top_bullish = _build_top_trades_by_ticker(flat_trades, 'BUY', 10)
    
    # Top bearish trades (one per ticker)
    top_bearish = _build_top_trades_by_ticker(flat_trades, 'SELL', 10)
    
    # Dark pool totals
    dark_pool_value = sum(t.get('value', 0) for t in dark_pool_trades)
    lit_value = sum(t.get('value', 0) for t in lit_trades)
    total_value = dark_pool_value + lit_value
    
    return {
        "_README": generate_readme_section(config),
        "metadata": metadata,
        "overall_sentiment": {
            "direction": overall_sentiment['direction'],
            "high_confidence_direction": overall_sentiment['high_confidence_direction'],
            "buy_value": overall_sentiment['buy_value'],
            "sell_value": overall_sentiment['sell_value'],
            "net_value": overall_sentiment['net_value'],
            "buy_sell_ratio": overall_sentiment['buy_sell_ratio'],
            "buy_count": overall_sentiment['buy_count'],
            "sell_count": overall_sentiment['sell_count'],
            "total_whale_trades": len(flat_trades),
            "hc_buy_count": overall_sentiment['hc_buy_count'],
            "hc_sell_count": overall_sentiment['hc_sell_count'],
            "hc_buy_value": overall_sentiment['hc_buy_value'],
            "hc_sell_value": overall_sentiment['hc_sell_value'],
            "hc_net_value": overall_sentiment['hc_net_value']
        },
        "dark_pool_sentiment": {
            "description": "Dark pool trades (Exchange D) - typically institutional block trades",
            "direction": dark_pool_sentiment['direction'],
            "high_confidence_direction": dark_pool_sentiment['high_confidence_direction'],
            "trade_count": len(dark_pool_trades),
            "total_value": dark_pool_value,
            "pct_of_whale_volume": round(dark_pool_value / total_value * 100, 1) if total_value > 0 else 0,
            "buy_value": dark_pool_sentiment['buy_value'],
            "sell_value": dark_pool_sentiment['sell_value'],
            "net_value": dark_pool_sentiment['net_value'],
            "buy_sell_ratio": dark_pool_sentiment['buy_sell_ratio'],
            "hc_buy_value": dark_pool_sentiment['hc_buy_value'],
            "hc_sell_value": dark_pool_sentiment['hc_sell_value'],
            "hc_net_value": dark_pool_sentiment['hc_net_value']
        },
        "lit_exchange_sentiment": {
            "description": "Lit exchange trades (public exchanges)",
            "direction": lit_sentiment['direction'],
            "high_confidence_direction": lit_sentiment['high_confidence_direction'],
            "trade_count": len(lit_trades),
            "total_value": lit_value,
            "pct_of_whale_volume": round(lit_value / total_value * 100, 1) if total_value > 0 else 0,
            "buy_value": lit_sentiment['buy_value'],
            "sell_value": lit_sentiment['sell_value'],
            "net_value": lit_sentiment['net_value'],
            "buy_sell_ratio": lit_sentiment['buy_sell_ratio']
        },
        "top_bullish_trades": {
            "description": "Top 10 tickers with largest BUY activity (one per ticker)",
            "trades": top_bullish
        },
        "top_bearish_trades": {
            "description": "Top 10 tickers with largest SELL activity (one per ticker)",
            "trades": top_bearish
        },
        "tier_breakdown": dict(tier_counts),
        "exchange_breakdown": exchange_breakdown,
        "sector_sentiment": sector_details,
        "top_sectors": [s[0] for s in sorted_sectors[:5] if s[1]['trade_count'] > 0]
    }


def build_trades_json(all_trades: Dict[str, List[Dict]], 
                      ticker_thresholds: Dict[str, Dict],
                      metadata: Dict, config: Dict) -> Dict:
    """
    Build the trades JSON output.
    
    Args:
        all_trades: Dictionary mapping ticker to list of whale trades
        ticker_thresholds: Dictionary mapping ticker to effective threshold
        metadata: Collection metadata
        config: Configuration dictionary
        
    Returns:
        Trades JSON dictionary
    """
    high_conf_threshold = config.get('direction', {}).get('high_confidence_threshold', 80)
    
    # Build by_ticker section
    by_ticker = {}
    
    for ticker, trades in sorted(all_trades.items()):
        if not trades:
            continue
        
        sentiment = calculate_sentiment(trades, high_conf_threshold)
        
        # Dark pool stats
        dark_pool_trades = [t for t in trades if t.get('is_dark_pool')]
        dark_pool_value = sum(t.get('value', 0) for t in dark_pool_trades)
        total_value = sum(t.get('value', 0) for t in trades)
        
        # Sort trades by value descending
        sorted_trades = sorted(trades, key=lambda x: x['value'], reverse=True)
        
        # Compact trade format
        compact_trades = []
        for t in sorted_trades:
            compact_trade = {
                "timestamp": t.get('timestamp'),
                "price": t.get('price'),
                "shares": t.get('shares'),
                "value": t.get('value'),
                "exchange": t.get('exchange'),
                "is_dark_pool": t.get('is_dark_pool'),
                "direction": t.get('direction'),
                "direction_confidence": t.get('direction_confidence'),
                "tier": t.get('tier_label', t.get('tier'))
            }
            compact_trades.append(compact_trade)
        
        threshold = ticker_thresholds.get(ticker, {})
        
        by_ticker[ticker] = {
            "sentiment": sentiment['direction'],
            "high_confidence_sentiment": sentiment['high_confidence_direction'],
            "buy_value": sentiment['buy_value'],
            "sell_value": sentiment['sell_value'],
            "net_value": sentiment['net_value'],
            "buy_sell_ratio": sentiment['buy_sell_ratio'],
            "trade_count": len(trades),
            "dark_pool_count": len(dark_pool_trades),
            "dark_pool_value": dark_pool_value,
            "dark_pool_pct": round(dark_pool_value / total_value * 100, 1) if total_value > 0 else 0,
            "sector": get_sector(ticker),
            "industry": get_industry(ticker),
            "sub_industry": get_sub_industry(ticker),
            "effective_threshold": {
                "shares": threshold.get('shares', config['thresholds']['minimum_shares']),
                "value": threshold.get('value', config['thresholds']['minimum_value'])
            },
            "trades": compact_trades
        }
    
    return {
        "_README": {
            "title": "S&P 500 Stock Whale Trades - Per-Ticker Details",
            "description": "Individual whale trades grouped by ticker with sentiment analysis",
            "dark_pool_note": "is_dark_pool=true indicates institutional off-exchange trade"
        },
        "metadata": metadata,
        "by_ticker": by_ticker
    }


# =============================================================================
# MAIN COLLECTION LOGIC
# =============================================================================

def collect_whale_trades(tickers: List[str], config: Dict, verbose: bool = True) -> Tuple[Dict, Dict, Dict]:
    """
    Main collection function - fetches whale trades for all tickers.
    
    Args:
        tickers: List of ticker symbols to scan
        config: Configuration dictionary
        verbose: Print progress messages
        
    Returns:
        Tuple of (all_trades, ticker_thresholds, metadata)
    """
    # Get API credentials
    api_key = os.getenv('ALPACA_API_KEY') or os.getenv('APCA-API-KEY-ID')
    api_secret = os.getenv('ALPACA_API_SECRET') or os.getenv('APCA-API-SECRET-KEY')
    
    if not api_key or not api_secret:
        raise ValueError("Missing Alpaca API credentials. Set ALPACA_API_KEY and ALPACA_API_SECRET environment variables.")
    
    # Initialize client
    rate_limiter = RateLimiter(config['rate_limiting']['max_requests_per_minute'])
    client = AlpacaStockClient(api_key, api_secret, rate_limiter)
    
    # Calculate lookback period
    lookback_days = config['collection']['lookback_trading_days']
    start_date = get_lookback_start_date(lookback_days)
    end_date = datetime.now()
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Stock Whale Collector")
        print(f"{'='*60}")
        print(f"Tickers to scan: {len(tickers)}")
        print(f"Lookback: {lookback_days} trading days")
        print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"Min threshold: {config['thresholds']['minimum_shares']:,} shares OR ${config['thresholds']['minimum_value']:,}")
        print(f"{'='*60}\n")
    
    # Collect trades
    all_trades = {}
    ticker_thresholds = {}
    total_raw_trades = 0
    total_whale_trades = 0
    skipped_tickers = []
    
    for i, ticker in enumerate(tickers, 1):
        if verbose:
            print(f"[{i}/{len(tickers)}] Scanning {ticker}...", end=" ", flush=True)
        
        try:
            # Process trades for this ticker
            whale_trades, raw_count = process_trades_for_ticker(
                client, ticker, start_date, config
            )
            
            total_raw_trades += raw_count
            
            if whale_trades:
                # Apply dynamic threshold
                threshold, filtered_trades = apply_dynamic_threshold(whale_trades, ticker, config)
                
                if filtered_trades:
                    all_trades[ticker] = filtered_trades
                    ticker_thresholds[ticker] = threshold
                    total_whale_trades += len(filtered_trades)
                    
                    # Count dark pool
                    dark_pool_count = sum(1 for t in filtered_trades if t.get('is_dark_pool'))
                    
                    if verbose:
                        print(f"found {len(filtered_trades)} whales ({dark_pool_count} dark pool)")
                else:
                    if verbose:
                        print(f"no trades above threshold")
            else:
                if verbose:
                    print(f"no whale trades")
                    
        except Exception as e:
            if verbose:
                print(f"error: {e}")
            skipped_tickers.append(ticker)
        
        # Small delay between tickers
        time.sleep(config['rate_limiting'].get('batch_delay', 0.5))
    
    # Build metadata
    metadata = {
        "collection_timestamp": datetime.now().isoformat(),
        "lookback_start": start_date.isoformat(),
        "lookback_end": end_date.isoformat(),
        "trading_days": get_trading_day_count(start_date, end_date),
        "tickers_scanned": len(tickers),
        "tickers_with_whales": len(all_trades),
        "tickers_skipped": len(skipped_tickers),
        "total_raw_trades_scanned": total_raw_trades,
        "total_whale_trades": total_whale_trades,
        "minimum_share_threshold": config['thresholds']['minimum_shares'],
        "minimum_value_threshold": config['thresholds']['minimum_value']
    }
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Collection Complete")
        print(f"{'='*60}")
        print(f"Tickers with whale activity: {len(all_trades)}/{len(tickers)}")
        print(f"Total whale trades found: {total_whale_trades:,}")
        print(f"Raw trades scanned: {total_raw_trades:,}")
        if skipped_tickers:
            print(f"Skipped tickers: {', '.join(skipped_tickers[:10])}{'...' if len(skipped_tickers) > 10 else ''}")
        print(f"{'='*60}\n")
    
    return all_trades, ticker_thresholds, metadata


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Stock Whale Collector')
    parser.add_argument('--test', action='store_true', help='Test mode with 5 tickers')
    parser.add_argument('--tickers', type=str, help='Comma-separated list of tickers')
    parser.add_argument('--output-dir', type=str, help='Output directory for JSON files')
    parser.add_argument('--quiet', action='store_true', help='Suppress progress output')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config()
    
    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Default to current script directory (same as optionswhales pattern)
        output_dir = Path(__file__).parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine tickers to scan
    if args.tickers:
        tickers = dedupe_company_tickers([t.strip().upper() for t in args.tickers.split(',')])
    elif args.test:
        tickers = dedupe_company_tickers(['AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOGL'])
    else:
        # Get S&P 500 tickers
        tickers = dedupe_company_tickers(get_spx_tickers())
    
    verbose = not args.quiet
    
    # Collect whale trades
    all_trades, ticker_thresholds, metadata = collect_whale_trades(tickers, config, verbose)
    
    # Build JSON outputs
    summary_json = build_summary_json(all_trades, metadata, config)
    trades_json = build_trades_json(all_trades, ticker_thresholds, metadata, config)
    
    # Save JSON files
    summary_path = output_dir / "stock_whale_summary.json"
    trades_path = output_dir / "stock_whale_trades.json"
    
    with open(summary_path, 'w') as f:
        json.dump(summary_json, f, indent=2, default=str)
    
    with open(trades_path, 'w') as f:
        json.dump(trades_json, f, indent=2, default=str)
    
    if verbose:
        print(f"Saved summary to: {summary_path}")
        print(f"Saved trades to: {trades_path}")
        
        # Print summary stats
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        
        overall = summary_json.get('overall_sentiment', {})
        print(f"Overall Sentiment: {overall.get('direction', 'N/A')}")
        print(f"  Buy Value: ${overall.get('buy_value', 0):,.0f}")
        print(f"  Sell Value: ${overall.get('sell_value', 0):,.0f}")
        print(f"  Net Value: ${overall.get('net_value', 0):,.0f}")
        
        dark_pool = summary_json.get('dark_pool_sentiment', {})
        print(f"\nDark Pool Sentiment: {dark_pool.get('direction', 'N/A')}")
        print(f"  Trades: {dark_pool.get('trade_count', 0)}")
        print(f"  Value: ${dark_pool.get('total_value', 0):,.0f} ({dark_pool.get('pct_of_whale_volume', 0)}% of whale volume)")
        print(f"  Net Value: ${dark_pool.get('net_value', 0):,.0f}")
        
        print(f"\nTop Sectors: {', '.join(summary_json.get('top_sectors', []))}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
