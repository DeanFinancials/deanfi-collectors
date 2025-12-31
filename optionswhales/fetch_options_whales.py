#!/usr/bin/env python3
"""
Options Whale Collector

Fetches large OTM options trades ("whale trades") for S&P 500 constituents
using the Alpaca Markets Options API.

Outputs:
- options_whale_summary.json: Aggregate summary data with sector breakdowns
- options_whale_trades.json: Per-ticker whale trades with detailed info

Environment Variables Required:
- ALPACA_API_KEY: Alpaca API Key ID
- ALPACA_API_SECRET: Alpaca API Secret Key

Usage:
    python fetch_options_whales.py                    # Full S&P 500 scan
    python fetch_options_whales.py --test             # Test with 5 tickers
    python fetch_options_whales.py --tickers AAPL,MSFT,NVDA  # Custom tickers
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

from utils import (
    get_lookback_start_date,
    get_trading_day_count,
    parse_option_symbol,
    calculate_days_to_expiration,
    calculate_moneyness,
    find_optimal_threshold,
    get_ticker_multiplier,
    classify_trade_tier,
    build_trade_flags,
    get_dte_bucket,
    detect_sweeps,
    RateLimiter,
    calculate_sentiment,
    calculate_sector_sentiment,
    aggregate_by_dte_bucket,
    format_currency,
    safe_round,
    convert_ticker_for_alpaca,
    convert_ticker_from_alpaca
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

class AlpacaOptionsClient:
    """Client for Alpaca Markets Options API."""
    
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
    
    def get_option_chain(self, underlying: str, limit: int = 500) -> Dict:
        """
        Fetch option chain for an underlying stock.
        
        Args:
            underlying: Stock ticker symbol
            limit: Maximum contracts to return
            
        Returns:
            Dictionary of option snapshots
        """
        endpoint = f"/v1beta1/options/snapshots/{underlying}"
        params = {'feed': 'indicative', 'limit': limit}
        
        response = self._request(endpoint, params)
        return response.get('snapshots', {}) if response else {}
    
    def get_option_trades(self, symbols: List[str], start_date: datetime, 
                         end_date: datetime = None) -> Dict:
        """
        Fetch historical trades for option contracts.
        
        Args:
            symbols: List of option contract symbols
            start_date: Start of time range
            end_date: End of time range (default: now)
            
        Returns:
            Dictionary mapping symbol to list of trades
        """
        if not symbols:
            return {}
        
        # API limit is 100 symbols per request
        symbols = symbols[:100]
        
        endpoint = "/v1beta1/options/trades"
        params = {
            'symbols': ','.join(symbols),
            'start': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'limit': 10000,
            'sort': 'desc'
        }
        
        if end_date:
            params['end'] = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        response = self._request(endpoint, params)
        return response.get('trades', {}) if response else {}
    
    def get_stock_price(self, symbol: str) -> float:
        """
        Get current stock price.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Current price or 0 on error
        """
        endpoint = f"/v2/stocks/{symbol}/trades/latest"
        
        response = self._request(endpoint)
        if response and 'trade' in response:
            return response['trade'].get('p', 0)
        return 0


# =============================================================================
# TRADE PROCESSING
# =============================================================================

def process_trades_for_ticker(client: AlpacaOptionsClient, ticker: str, 
                              start_date: datetime, config: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Process all option trades for a single ticker.
    
    Fetches option chain, then trades for each contract, filters by moneyness,
    calculates premium, and applies dynamic thresholds.
    
    Args:
        client: AlpacaOptionsClient instance
        ticker: Stock ticker symbol
        start_date: Start of lookback period
        config: Configuration dictionary
        
    Returns:
        Tuple of (otm_trades, atm_trades) for sweep detection
    """
    otm_trades = []
    atm_trades = []
    
    # Get configuration values
    atm_threshold = config['collection']['atm_threshold_pct']
    
    # Get option chain
    chain = client.get_option_chain(ticker, limit=500)
    if not chain:
        return [], []
    
    # Get current stock price
    stock_price = client.get_stock_price(ticker)
    if stock_price <= 0:
        print(f"Could not get stock price for {ticker}")
        return [], []
    
    contracts = list(chain.keys())
    if not contracts:
        return [], []
    
    # Extract open interest from chain for vol/OI calculations
    chain_oi = {}
    for symbol, snap in chain.items():
        if 'latestQuote' in snap:
            # Estimate OI from quote size (Alpaca doesn't provide OI directly)
            quote = snap['latestQuote']
            chain_oi[symbol] = quote.get('bs', 0) + quote.get('as', 0)
    
    # Fetch trades in batches
    all_contract_trades = {}
    batch_size = config['rate_limiting']['options_batch_size']
    
    for i in range(0, len(contracts), batch_size):
        batch = contracts[i:i+batch_size]
        trades = client.get_option_trades(batch, start_date)
        all_contract_trades.update(trades)
    
    # Process each trade
    for contract_symbol, trades in all_contract_trades.items():
        parsed = parse_option_symbol(contract_symbol)
        if not parsed:
            continue
        
        for trade in trades:
            size = trade.get('s', 0)
            price = trade.get('p', 0)
            timestamp = trade.get('t', '')
            exchange = trade.get('x', '')
            
            if size <= 0 or price <= 0:
                continue
            
            # Calculate values
            premium = size * price * 100  # Options are 100 shares
            notional = size * parsed['strike'] * 100
            
            # Calculate DTE
            dte = calculate_days_to_expiration(parsed['expiration'])
            
            # Calculate moneyness
            itm_status, moneyness_pct = calculate_moneyness(
                stock_price, parsed['strike'], parsed['type'], atm_threshold
            )
            
            # Estimate vol/OI ratio
            oi = chain_oi.get(contract_symbol, 0)
            vol_oi_ratio = size / oi if oi > 0 else None
            
            # Build flags
            flags = build_trade_flags(
                vol_oi_ratio, dte,
                config['interpretation']['vol_oi_flags']['high_threshold'],
                config['interpretation']['vol_oi_flags']['notable_threshold']
            )
            
            # Build trade record
            trade_record = {
                'contract': contract_symbol,
                'underlying': ticker,
                'type': parsed['type'],
                'strike': parsed['strike'],
                'expiration': parsed['expiration_str'],
                'dte': dte,
                'timestamp': timestamp,
                'exchange': exchange,
                'contracts': size,
                'price': price,
                'premium': premium,
                'notional': notional,
                'stock_price': stock_price,
                'moneyness': itm_status,
                'moneyness_pct': safe_round(moneyness_pct, 2),
                'vol_oi_pct': safe_round(vol_oi_ratio * 100, 1) if vol_oi_ratio else None,
                'sentiment': 'BULLISH' if parsed['type'] == 'CALL' else 'BEARISH',
                'flags': flags,
                'is_sweep': False,
                'sweep_id': None
            }
            
            # Sort by moneyness
            if itm_status == 'OTM':
                otm_trades.append(trade_record)
            elif itm_status == 'ATM':
                atm_trades.append(trade_record)
            # Skip ITM trades
    
    return otm_trades, atm_trades


def apply_dynamic_threshold(trades: List[Dict], ticker: str, config: Dict) -> Tuple[int, List[Dict]]:
    """
    Apply dynamic threshold to a ticker's trades.
    
    Args:
        trades: List of trade dictionaries
        ticker: Stock ticker symbol
        config: Configuration dictionary
        
    Returns:
        Tuple of (effective_threshold, filtered_trades)
    """
    # Get ticker multiplier
    multiplier = get_ticker_multiplier(
        ticker,
        config['ticker_size'].get('classifications', {}),
        config['ticker_size']['multipliers']
    )
    
    # Apply dynamic threshold
    threshold, filtered = find_optimal_threshold(
        trades,
        config['thresholds']['tiers'],
        config['thresholds']['target_min'],
        config['thresholds']['target_max'],
        config['thresholds']['hard_max'],
        multiplier
    )
    
    # Add tier classification to each trade
    for trade in filtered:
        tier_info = classify_trade_tier(trade['premium'], config['thresholds']['tiers'], multiplier)
        trade['tier'] = tier_info['tier']
        trade['tier_label'] = tier_info['label']
        trade['tier_emoji'] = tier_info['emoji']
    
    return threshold, filtered


# =============================================================================
# JSON OUTPUT GENERATION
# =============================================================================

def generate_readme_section(config: Dict) -> Dict:
    """Generate the _README section for JSON outputs."""
    return {
        "title": "S&P 500 Options Whale Trades",
        "description": "Large OTM options trades detected over 5 trading days for S&P 500 constituents",
        "purpose": "Identify institutional-sized options bets for sentiment analysis and trade ideas",
        "data_source": "Alpaca Markets Options API",
        "methodology": {
            "lookback_days": config['collection']['lookback_trading_days'],
            "lookback_type": "Trading days (excludes weekends and NYSE holidays)",
            "moneyness_filter": "OTM only (>2% out of the money)",
            "threshold_approach": "Dynamic - starts at $100K minimum, steps up until <= 10 trades per ticker",
            "threshold_tiers": [format_currency(t) for t in config['thresholds']['tiers'][:6]],
            "max_trades_per_ticker": config['thresholds']['hard_max']
        },
        "field_descriptions": {
            "contract": "OCC option symbol (e.g., MS260116C00180000)",
            "premium": "Total premium paid = price × 100 × contracts",
            "notional": "Notional value controlled = strike × 100 × contracts",
            "dte": "Days to expiration from collection date",
            "moneyness_pct": "How far OTM the option is (negative = OTM)",
            "vol_oi_pct": "Trade size as percentage of estimated open interest",
            "is_sweep": "True if trade is part of a detected sweep order",
            "sweep_id": "Identifier linking trades in the same sweep",
            "effective_threshold": "The dynamic threshold applied to this ticker"
        },
        "sentiment_interpretation": {
            "BULLISH": "Call buying - betting stock price will increase",
            "BEARISH": "Put buying - betting stock price will decrease",
            "call_put_ratio": "Ratio > 1 = bullish bias, < 1 = bearish bias"
        },
        "tier_descriptions": config['interpretation']['tier_descriptions'],
        "dte_bucket_descriptions": config['interpretation']['dte_buckets'],
        "update_schedule": "Daily at Noon ET (mid-market) and 9 PM ET (post-market)"
    }


def _build_top_trades_by_ticker(trades: List[Dict], max_tickers: int = 10) -> List[Dict]:
    """
    Build a top trades list with one entry per ticker.
    
    For each ticker, shows its largest trade and counts how many additional
    trades it has above the next ticker's highest trade threshold.
    
    This prevents one heavily-traded ticker from dominating the top 10 while
    still conveying the depth of activity on that ticker.
    
    Args:
        trades: List of trade dictionaries (all same type - calls or puts)
        max_tickers: Maximum number of tickers to include
        
    Returns:
        List of trade summaries, one per ticker
    """
    if not trades:
        return []
    
    # Group trades by ticker and sort each group by premium descending
    trades_by_ticker = defaultdict(list)
    for t in trades:
        ticker = t.get('underlying')
        if ticker:
            trades_by_ticker[ticker].append(t)
    
    # Sort trades within each ticker by premium (highest first)
    for ticker in trades_by_ticker:
        trades_by_ticker[ticker].sort(key=lambda x: x.get('premium', 0), reverse=True)
    
    # Get the highest trade for each ticker and sort tickers by their max premium
    ticker_max_trades = []
    for ticker, ticker_trades in trades_by_ticker.items():
        if ticker_trades:
            ticker_max_trades.append({
                'ticker': ticker,
                'max_trade': ticker_trades[0],
                'max_premium': ticker_trades[0].get('premium', 0),
                'all_trades': ticker_trades
            })
    
    # Sort by max premium descending
    ticker_max_trades.sort(key=lambda x: x['max_premium'], reverse=True)
    
    # Take top N tickers
    top_tickers = ticker_max_trades[:max_tickers]
    
    # Build result with additional trade counts
    result = []
    for i, entry in enumerate(top_tickers):
        ticker = entry['ticker']
        max_trade = entry['max_trade']
        all_trades = entry['all_trades']
        
        # Determine threshold: next ticker's highest trade, or 0 if last
        if i + 1 < len(top_tickers):
            next_threshold = top_tickers[i + 1]['max_premium']
        else:
            # For the last ticker, use half of its own max as threshold
            # or a minimum sensible value
            next_threshold = min(entry['max_premium'] * 0.5, 100000)
        
        # Count additional trades above the threshold
        additional_above_threshold = sum(
            1 for t in all_trades[1:]  # Skip the first (shown) trade
            if t.get('premium', 0) > next_threshold
        )
        
        # Total premium for this ticker
        total_ticker_premium = sum(t.get('premium', 0) for t in all_trades)
        
        result.append({
            "ticker": ticker,
            "contract": max_trade.get('contract'),
            "strike": max_trade.get('strike'),
            "expiration": max_trade.get('expiration'),
            "dte": max_trade.get('dte'),
            "premium": max_trade.get('premium'),
            "contracts": max_trade.get('contracts'),
            "tier": max_trade.get('tier_label', max_trade.get('tier')),
            "sector": get_sector(ticker),
            "industry": get_industry(ticker),
            "sub_industry": get_sub_industry(ticker),
            "total_trades": len(all_trades),
            "additional_above_threshold": additional_above_threshold,
            "threshold_comparison": round(next_threshold, 2),
            "total_ticker_premium": round(total_ticker_premium, 2)
        })
    
    return result


def build_summary_json(all_trades: Dict[str, List[Dict]], sweeps: List[Dict], 
                       metadata: Dict, config: Dict) -> Dict:
    """
    Build the summary JSON output.
    
    Args:
        all_trades: Dictionary mapping ticker to list of whale trades
        sweeps: List of detected sweeps
        metadata: Collection metadata
        config: Configuration dictionary
        
    Returns:
        Summary JSON dictionary
    """
    # Flatten all trades for aggregate calculations
    flat_trades = []
    for ticker_trades in all_trades.values():
        flat_trades.extend(ticker_trades)
    
    # Calculate overall sentiment
    overall_sentiment = calculate_sentiment(flat_trades)
    
    # Calculate big whale sentiment ($250K+)
    big_whale_trades = [t for t in flat_trades if t.get('premium', 0) >= 250000]
    big_whale_sentiment = calculate_sentiment(big_whale_trades)
    
    # Calculate sector sentiment
    trades_by_ticker = {ticker: trades for ticker, trades in all_trades.items()}
    sector_sentiment = calculate_sector_sentiment(trades_by_ticker)
    
    # Sort sectors by total activity
    sorted_sectors = sorted(
        sector_sentiment.items(),
        key=lambda x: x[1]['call_premium'] + x[1]['put_premium'],
        reverse=True
    )
    
    # Build sector details
    sector_details = {}
    for sector, sentiment in sorted_sectors:
        if sentiment['trade_count'] > 0:
            sector_details[sector] = {
                "sentiment": sentiment['direction'],
                "call_premium": sentiment['call_premium'],
                "put_premium": sentiment['put_premium'],
                "call_put_ratio": sentiment['call_put_ratio'],
                "call_count": sentiment['call_count'],
                "put_count": sentiment['put_count'],
                "trade_count": sentiment['trade_count'],
                "ticker_count": sentiment['ticker_count'],
                "net_premium": sentiment['net_premium']
            }
    
    # Calculate DTE breakdown
    dte_breakdown = aggregate_by_dte_bucket(flat_trades)
    
    # Tier breakdown
    tier_counts = defaultdict(lambda: {'count': 0, 'premium': 0})
    for trade in flat_trades:
        tier = trade.get('tier', 'unknown')
        tier_counts[tier]['count'] += 1
        tier_counts[tier]['premium'] += trade.get('premium', 0)
    
    # Sweeps summary
    bullish_sweeps = [s for s in sweeps if s['sentiment'] == 'BULLISH']
    bearish_sweeps = [s for s in sweeps if s['sentiment'] == 'BEARISH']
    
    # Top 10 bullish trades - one per ticker with additional trade count
    top_bullish = _build_top_trades_by_ticker(
        [t for t in flat_trades if t.get('type') == 'CALL'],
        max_tickers=10
    )
    
    # Top 10 bearish trades - one per ticker with additional trade count
    top_bearish = _build_top_trades_by_ticker(
        [t for t in flat_trades if t.get('type') == 'PUT'],
        max_tickers=10
    )
    
    return {
        "_README": generate_readme_section(config),
        "metadata": metadata,
        "overall_sentiment": {
            "direction": overall_sentiment['direction'],
            "call_premium_total": overall_sentiment['call_premium'],
            "put_premium_total": overall_sentiment['put_premium'],
            "call_put_ratio": overall_sentiment['call_put_ratio'],
            "call_count": overall_sentiment['call_count'],
            "put_count": overall_sentiment['put_count'],
            "total_whale_trades": len(flat_trades),
            "net_premium": overall_sentiment['net_premium']
        },
        "big_whale_sentiment": {
            "description": "Trades with premium >= $250K",
            "direction": big_whale_sentiment['direction'],
            "call_premium": big_whale_sentiment['call_premium'],
            "put_premium": big_whale_sentiment['put_premium'],
            "call_put_ratio": big_whale_sentiment['call_put_ratio'],
            "trade_count": len(big_whale_trades)
        },
        "top_bullish_trades": {
            "description": "Top 10 tickers with largest call trades (one per ticker, bullish bets)",
            "trades": top_bullish
        },
        "top_bearish_trades": {
            "description": "Top 10 tickers with largest put trades (one per ticker, bearish bets)",
            "trades": top_bearish
        },
        "tier_breakdown": dict(tier_counts),
        "expiration_breakdown": dte_breakdown,
        "sector_sentiment": sector_details,
        "top_sectors": [s[0] for s in sorted_sectors[:5] if s[1]['trade_count'] > 0],
        "sweeps_summary": {
            "total_count": len(sweeps),
            "total_premium": sum(s['total_premium'] for s in sweeps),
            "bullish_count": len(bullish_sweeps),
            "bullish_premium": sum(s['total_premium'] for s in bullish_sweeps),
            "bearish_count": len(bearish_sweeps),
            "bearish_premium": sum(s['total_premium'] for s in bearish_sweeps)
        }
    }


def build_trades_json(all_trades: Dict[str, List[Dict]], 
                      ticker_thresholds: Dict[str, int],
                      sweeps: List[Dict], 
                      metadata: Dict, 
                      config: Dict) -> Dict:
    """
    Build the trades JSON output.
    
    Only stores whale trades (above threshold) - no raw trade data.
    Sweeps are summarized, not stored in full.
    
    Args:
        all_trades: Dictionary mapping ticker to list of whale trades (already filtered)
        ticker_thresholds: Dictionary mapping ticker to effective threshold
        sweeps: List of detected sweeps (from whale trades only)
        metadata: Collection metadata
        config: Configuration dictionary
        
    Returns:
        Trades JSON dictionary
    """
    # Build by_ticker section with per-ticker summaries
    by_ticker = {}
    
    for ticker, trades in sorted(all_trades.items()):
        if not trades:
            continue
        
        sentiment = calculate_sentiment(trades)
        stock_price = trades[0].get('stock_price', 0) if trades else 0
        
        # Get ticker size category
        size_class = config['ticker_size'].get('classifications', {}).get(ticker, 'mid')
        
        # Sort trades by premium descending
        sorted_trades = sorted(trades, key=lambda x: x['premium'], reverse=True)
        
        # Compact trade format - remove verbose fields
        compact_trades = []
        for t in sorted_trades:
            compact_trade = {
                "contract": t.get('contract'),
                "type": t.get('type'),
                "strike": t.get('strike'),
                "expiration": t.get('expiration'),
                "dte": t.get('dte'),
                "premium": t.get('premium'),
                "contracts": t.get('contracts'),
                "tier": t.get('tier_label', t.get('tier')),
                "timestamp": t.get('timestamp'),
            }
            # Only include sweep info if trade is part of a sweep
            if t.get('is_sweep'):
                compact_trade['is_sweep'] = True
                compact_trade['sweep_id'] = t.get('sweep_id')
            compact_trades.append(compact_trade)
        
        by_ticker[ticker] = {
            "sentiment": sentiment['direction'],
            "call_premium": sentiment['call_premium'],
            "put_premium": sentiment['put_premium'],
            "call_put_ratio": sentiment['call_put_ratio'],
            "trade_count": len(trades),
            "stock_price": stock_price,
            "sector": get_sector(ticker),
            "industry": get_industry(ticker),
            "sub_industry": get_sub_industry(ticker),
            "ticker_size": size_class,
            "effective_threshold": ticker_thresholds.get(ticker, config['thresholds']['minimum_threshold']),
            "trades": compact_trades
        }
    
    # Build sweep summary (don't store full sweep details, just counts and top sweeps)
    bullish_sweeps = [s for s in sweeps if s['sentiment'] == 'BULLISH']
    bearish_sweeps = [s for s in sweeps if s['sentiment'] == 'BEARISH']
    
    # Top 10 sweeps by premium (compact format)
    top_sweeps = []
    for s in sorted(sweeps, key=lambda x: x['total_premium'], reverse=True)[:10]:
        top_sweeps.append({
            "underlying": s['underlying'],
            "legs": s['legs'],
            "total_premium": s['total_premium'],
            "total_contracts": s['total_contracts'],
            "sentiment": s['sentiment'],
            "strikes": s['strikes'][:5] if len(s['strikes']) > 5 else s['strikes'],  # Limit strikes shown
        })
    
    sweeps_summary = {
        "total_count": len(sweeps),
        "total_premium": sum(s['total_premium'] for s in sweeps),
        "bullish_count": len(bullish_sweeps),
        "bullish_premium": sum(s['total_premium'] for s in bullish_sweeps),
        "bearish_count": len(bearish_sweeps),
        "bearish_premium": sum(s['total_premium'] for s in bearish_sweeps),
        "top_sweeps": top_sweeps
    }
    
    return {
        "_README": generate_readme_section(config),
        "metadata": metadata,
        "sweeps_summary": sweeps_summary,
        "by_ticker": by_ticker
    }


# =============================================================================
# MAIN COLLECTION LOGIC
# =============================================================================

def collect_options_whales(tickers: List[str], config: Dict, 
                          api_key: str, api_secret: str) -> Tuple[Dict, Dict]:
    """
    Main collection function - fetches and processes whale trades.
    
    Args:
        tickers: List of ticker symbols to scan
        config: Configuration dictionary
        api_key: Alpaca API Key
        api_secret: Alpaca API Secret
        
    Returns:
        Tuple of (summary_json, trades_json)
    """
    # Initialize rate limiter
    rate_limiter = RateLimiter(
        max_requests_per_minute=config['rate_limiting']['max_requests_per_minute'],
        min_delay_seconds=config['rate_limiting']['delay_between_tickers']
    )
    
    # Initialize API client
    client = AlpacaOptionsClient(api_key, api_secret, rate_limiter)
    
    # Calculate lookback period
    trading_days = config['collection']['lookback_trading_days']
    start_date = get_lookback_start_date(trading_days)
    end_date = datetime.now()
    
    print(f"\n{'='*60}")
    print(f"OPTIONS WHALE COLLECTOR")
    print(f"{'='*60}")
    print(f"Tickers to scan: {len(tickers)}")
    print(f"Lookback: {trading_days} trading days")
    print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Rate limit: {config['rate_limiting']['max_requests_per_minute']} req/min")
    print(f"{'='*60}\n")
    
    # Collect trades for each ticker
    all_trades = {}  # Only stores whale trades above threshold
    ticker_thresholds = {}
    
    tickers_with_whales = 0
    total_whale_trades = 0
    skipped_tickers = 0
    
    for i, ticker in enumerate(tickers, 1):
        # Convert ticker to Alpaca format
        alpaca_ticker = convert_ticker_for_alpaca(ticker)
        
        # Skip problematic tickers
        if alpaca_ticker is None:
            print(f"[{i}/{len(tickers)}] Skipping {ticker} (not supported)")
            skipped_tickers += 1
            continue
        
        # Use original ticker for display, alpaca ticker for API
        display_ticker = ticker
        print(f"[{i}/{len(tickers)}] Scanning {display_ticker}...", end=" ", flush=True)
        
        try:
            # Get OTM and ATM trades (use alpaca_ticker for API call)
            otm_trades, atm_trades = process_trades_for_ticker(
                client, alpaca_ticker, start_date, config
            )
            
            # Convert ticker back to standard format in trade records
            for trade in otm_trades:
                trade['underlying'] = display_ticker
            
            if otm_trades:
                # Apply dynamic threshold
                threshold, filtered_trades = apply_dynamic_threshold(
                    otm_trades, display_ticker, config
                )
                
                if filtered_trades:
                    all_trades[display_ticker] = filtered_trades
                    ticker_thresholds[display_ticker] = threshold
                    tickers_with_whales += 1
                    total_whale_trades += len(filtered_trades)
                    print(f"found {len(filtered_trades)} trades (threshold: {format_currency(threshold)})")
                else:
                    print(f"no trades above threshold")
            else:
                print(f"no OTM trades")
                
        except Exception as e:
            error_msg = str(e)
            # Don't log full error for expected "no options" situations
            if "invalid underlying" in error_msg.lower() or "not found" in error_msg.lower():
                print(f"no options available")
            else:
                print(f"error: {error_msg[:50]}")
    
    # Detect sweeps from WHALE trades only (trades above threshold)
    print(f"\nDetecting sweeps among whale trades...")
    whale_trades_flat = []
    for ticker_trades in all_trades.values():
        whale_trades_flat.extend(ticker_trades)
    
    sweeps = detect_sweeps(
        whale_trades_flat,
        config['sweeps']['time_window_seconds'],
        config['sweeps']['min_legs']
    )
    print(f"Found {len(sweeps)} sweeps among {len(whale_trades_flat)} whale trades")
    
    # Update trades with sweep info
    sweep_trade_ids = set()
    for sweep in sweeps:
        for trade_id in sweep.get('trade_ids', []):
            sweep_trade_ids.add(trade_id)
    
    for ticker_trades in all_trades.values():
        for trade in ticker_trades:
            if trade['contract'] in sweep_trade_ids:
                trade['is_sweep'] = True
                # Find sweep_id
                for sweep in sweeps:
                    if trade['contract'] in sweep.get('trade_ids', []):
                        trade['sweep_id'] = sweep['sweep_id']
                        break
    
    # Build metadata
    metadata = {
        "generated_at": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        "lookback_start": start_date.strftime('%Y-%m-%d'),
        "lookback_end": end_date.strftime('%Y-%m-%d'),
        "trading_days": trading_days,
        "data_source": "Alpaca Markets Options API",
        "tickers_scanned": len(tickers),
        "tickers_with_whales": tickers_with_whales,
        "total_whale_trades": total_whale_trades,
        "sweeps_detected": len(sweeps)
    }
    
    # Build JSON outputs
    summary_json = build_summary_json(all_trades, sweeps, metadata, config)
    trades_json = build_trades_json(all_trades, ticker_thresholds, sweeps, metadata, config)
    
    return summary_json, trades_json


def save_json(data: Dict, filepath: Path):
    """Save dictionary to JSON file with pretty formatting."""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Saved: {filepath}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Options Whale Collector')
    parser.add_argument('--test', action='store_true', 
                       help='Test mode with 5 sample tickers')
    parser.add_argument('--tickers', type=str, 
                       help='Comma-separated list of tickers to scan')
    parser.add_argument('--output-dir', type=str, 
                       help='Output directory for JSON files')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config()
    
    # Get API keys from environment
    api_key = os.environ.get(config['api_keys']['api_key_env'])
    api_secret = os.environ.get(config['api_keys']['api_secret_env'])
    
    if not api_key or not api_secret:
        print(f"Error: Missing API keys. Please set environment variables:")
        print(f"  - {config['api_keys']['api_key_env']}")
        print(f"  - {config['api_keys']['api_secret_env']}")
        sys.exit(1)
    
    # Determine tickers to scan
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
        print(f"Using custom tickers: {tickers}")
    elif args.test:
        tickers = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'META']
        print(f"Test mode - using sample tickers: {tickers}")
    else:
        tickers = get_spx_tickers()
        print(f"Scanning full S&P 500 ({len(tickers)} tickers)")
    
    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Default to local directory (for GitHub Actions workflow compatibility)
        output_dir = Path(__file__).parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run collection
    start_time = time.time()
    summary_json, trades_json = collect_options_whales(tickers, config, api_key, api_secret)
    elapsed = time.time() - start_time
    
    # Save outputs
    summary_path = output_dir / config['output']['summary_file']
    trades_path = output_dir / config['output']['trades_file']
    
    save_json(summary_json, summary_path)
    save_json(trades_json, trades_path)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"COLLECTION COMPLETE")
    print(f"{'='*60}")
    print(f"Time elapsed: {elapsed:.1f} seconds")
    print(f"Tickers scanned: {summary_json['metadata']['tickers_scanned']}")
    print(f"Tickers with whales: {summary_json['metadata']['tickers_with_whales']}")
    print(f"Total whale trades: {summary_json['metadata']['total_whale_trades']}")
    print(f"Sweeps detected: {summary_json['metadata']['sweeps_detected']}")
    print(f"\nOverall Sentiment: {summary_json['overall_sentiment']['direction']}")
    print(f"  Call Premium: {format_currency(summary_json['overall_sentiment']['call_premium_total'])}")
    print(f"  Put Premium: {format_currency(summary_json['overall_sentiment']['put_premium_total'])}")
    print(f"  Call/Put Ratio: {summary_json['overall_sentiment']['call_put_ratio']}")
    print(f"\nTop Sectors: {', '.join(summary_json['top_sectors'][:3])}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
