"""
Options Whale Collector Utilities

Helper functions for:
- Trading day calculations (using NYSE calendar)
- Dynamic threshold optimization
- Sweep detection
- Rate limiting
- Option symbol parsing
- Trade classification
"""

import re
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from collections import defaultdict
from functools import wraps
from shared.sector_mapping import get_sector

# Try to import pandas_market_calendars for NYSE trading days
try:
    import pandas_market_calendars as mcal
    HAS_MARKET_CALENDAR = True
except ImportError:
    HAS_MARKET_CALENDAR = False
    print("Warning: pandas_market_calendars not installed. Using fallback trading day calculation.")

import pandas as pd


# =============================================================================
# TICKER FORMAT CONVERSION
# =============================================================================

# Tickers that need special handling for Alpaca API
# Alpaca uses dot notation (BRK.B) while Yahoo/SEC use dash (BRK-B)
ALPACA_TICKER_MAP = {
    "BRK-B": "BRK.B",  # Berkshire Hathaway Class B
    "BF-B": "BF.B",    # Brown-Forman Class B
}

# Reverse map for converting back
ALPACA_TICKER_REVERSE = {v: k for k, v in ALPACA_TICKER_MAP.items()}

# Tickers to skip entirely (no options or problematic)
SKIP_TICKERS = {
    "BRK.A",  # Berkshire Class A - extremely high price, no liquid options
    "BRK-A",
}


def convert_ticker_for_alpaca(ticker: str) -> Optional[str]:
    """
    Convert ticker symbol to Alpaca API format.
    
    Alpaca uses dot notation for share classes (BRK.B, BF.B)
    while Yahoo Finance and others use dash notation (BRK-B, BF-B).
    
    Args:
        ticker: Ticker symbol in standard format (e.g., BRK-B)
        
    Returns:
        Alpaca-compatible ticker, or None if should be skipped
    """
    # Skip problematic tickers
    if ticker in SKIP_TICKERS:
        return None
    
    # Apply known conversions
    if ticker in ALPACA_TICKER_MAP:
        return ALPACA_TICKER_MAP[ticker]
    
    # Convert any remaining dashes in class notation to dots
    # e.g., "XXX-A" -> "XXX.A" for share classes
    if '-' in ticker and len(ticker.split('-')[-1]) == 1:
        return ticker.replace('-', '.')
    
    return ticker


def convert_ticker_from_alpaca(ticker: str) -> str:
    """
    Convert ticker from Alpaca format back to standard format.
    
    Args:
        ticker: Ticker in Alpaca format (e.g., BRK.B)
        
    Returns:
        Standard format ticker (e.g., BRK-B)
    """
    if ticker in ALPACA_TICKER_REVERSE:
        return ALPACA_TICKER_REVERSE[ticker]
    
    # Convert dots back to dashes for share classes
    if '.' in ticker and len(ticker.split('.')[-1]) == 1:
        return ticker.replace('.', '-')
    
    return ticker


# =============================================================================
# TRADING DAY UTILITIES
# =============================================================================

def get_nyse_trading_days(start_date: datetime, end_date: datetime) -> List[datetime]:
    """
    Get list of NYSE trading days between start and end dates.
    
    Uses pandas_market_calendars for accurate holiday detection.
    Falls back to simple weekday calculation if not available.
    
    Args:
        start_date: Start of date range
        end_date: End of date range
        
    Returns:
        List of datetime objects representing trading days
    """
    if HAS_MARKET_CALENDAR:
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=start_date, end_date=end_date)
        return [d.to_pydatetime() for d in schedule.index]
    else:
        # Fallback: use pandas business days (doesn't account for holidays)
        dates = pd.bdate_range(start=start_date, end=end_date)
        return [d.to_pydatetime() for d in dates]


def get_lookback_start_date(trading_days: int = 5) -> datetime:
    """
    Calculate the start date for a given number of trading days lookback.
    
    Args:
        trading_days: Number of trading days to look back
        
    Returns:
        Start datetime for the lookback period
    """
    end_date = datetime.now()
    
    if HAS_MARKET_CALENDAR:
        nyse = mcal.get_calendar('NYSE')
        # Get more days than needed to ensure we have enough trading days
        buffer_days = trading_days * 2 + 10
        start_buffer = end_date - timedelta(days=buffer_days)
        schedule = nyse.schedule(start_date=start_buffer, end_date=end_date)
        
        if len(schedule) >= trading_days:
            # Return the date 'trading_days' ago
            return schedule.index[-(trading_days)].to_pydatetime()
        else:
            # Not enough trading days in range, return earliest
            return schedule.index[0].to_pydatetime()
    else:
        # Fallback: rough estimate (add buffer for weekends)
        calendar_days = int(trading_days * 1.5)
        return end_date - timedelta(days=calendar_days)


def get_trading_day_count(start_date: datetime, end_date: datetime) -> int:
    """
    Count the number of trading days between two dates.
    
    Args:
        start_date: Start date
        end_date: End date
        
    Returns:
        Number of trading days
    """
    trading_days = get_nyse_trading_days(start_date, end_date)
    return len(trading_days)


# =============================================================================
# OPTION SYMBOL PARSING
# =============================================================================

def parse_option_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Parse an OCC option symbol into its components.
    
    Format: AAPL251219C00275000
    - AAPL = underlying (1-6 chars)
    - 251219 = expiration YYMMDD (Dec 19, 2025)
    - C = Call (P = Put)
    - 00275000 = strike price $275.00 (divide by 1000)
    
    Args:
        symbol: OCC option symbol string
        
    Returns:
        Dictionary with parsed components, or None if invalid
    """
    # OCC format: up to 6 char underlying + 6 digit date + C/P + 8 digit strike
    pattern = r'^([A-Z]{1,6})(\d{6})([CP])(\d{8})$'
    match = re.match(pattern, symbol)
    
    if not match:
        return None
    
    underlying, date_str, opt_type, strike_str = match.groups()
    
    # Parse expiration date (YYMMDD)
    try:
        expiration = datetime.strptime(date_str, '%y%m%d')
    except ValueError:
        expiration = None
    
    # Parse strike (divide by 1000, last 3 digits are decimals)
    strike = int(strike_str) / 1000
    
    return {
        'underlying': underlying,
        'expiration': expiration,
        'expiration_str': expiration.strftime('%Y-%m-%d') if expiration else date_str,
        'type': 'CALL' if opt_type == 'C' else 'PUT',
        'type_code': opt_type,
        'strike': strike,
        'symbol': symbol
    }


def calculate_days_to_expiration(expiration: datetime) -> Optional[int]:
    """
    Calculate days to expiration from today.
    
    Args:
        expiration: Expiration datetime
        
    Returns:
        Number of days until expiration, or None if invalid
    """
    if expiration is None:
        return None
    return (expiration - datetime.now()).days


def calculate_moneyness(stock_price: float, strike: float, option_type: str, 
                        atm_threshold_pct: float = 2.0) -> Tuple[str, float]:
    """
    Determine if an option is ITM, ATM, or OTM.
    
    Args:
        stock_price: Current stock price
        strike: Option strike price
        option_type: 'CALL' or 'PUT'
        atm_threshold_pct: Percentage threshold for ATM classification
        
    Returns:
        Tuple of (status string, moneyness percentage)
    """
    if stock_price <= 0:
        return 'ATM', 0.0
    
    if option_type == 'CALL':
        # For calls: ITM when stock > strike
        moneyness_pct = (stock_price - strike) / stock_price * 100
    else:
        # For puts: ITM when strike > stock
        moneyness_pct = (strike - stock_price) / stock_price * 100
    
    if moneyness_pct > atm_threshold_pct:
        return 'ITM', moneyness_pct
    elif moneyness_pct < -atm_threshold_pct:
        return 'OTM', moneyness_pct
    else:
        return 'ATM', moneyness_pct


# =============================================================================
# DYNAMIC THRESHOLD LOGIC
# =============================================================================

def find_optimal_threshold(trades: List[Dict], 
                          threshold_tiers: List[int],
                          target_min: int = 5,
                          target_max: int = 10,
                          hard_max: int = 20,
                          ticker_multiplier: float = 1.0) -> Tuple[int, List[Dict]]:
    """
    Find the optimal threshold that yields target_min to target_max trades.
    
    Algorithm:
    1. Start at lowest tier (multiplied by ticker_multiplier)
    2. Filter trades >= threshold
    3. If count <= target_max, return those trades
    4. Otherwise, step up to next tier and repeat
    5. Return at most hard_max trades, sorted by premium descending
    
    Args:
        trades: List of trade dictionaries with 'premium' key
        threshold_tiers: List of premium thresholds in ascending order
        target_min: Minimum desired trades (informational only)
        target_max: Maximum desired trades (try to hit this or less)
        hard_max: Absolute maximum trades to return
        ticker_multiplier: Multiplier based on ticker size
        
    Returns:
        Tuple of (effective_threshold, filtered_trades)
    """
    # Sort trades by premium descending
    sorted_trades = sorted(trades, key=lambda x: x.get('premium', 0), reverse=True)
    
    for tier in threshold_tiers:
        adjusted_threshold = int(tier * ticker_multiplier)
        filtered = [t for t in sorted_trades if t.get('premium', 0) >= adjusted_threshold]
        
        if len(filtered) <= target_max:
            # Found good threshold, cap at hard_max just in case
            return adjusted_threshold, filtered[:hard_max]
    
    # If we exhausted all tiers, return top hard_max at highest threshold
    highest_threshold = int(threshold_tiers[-1] * ticker_multiplier)
    return highest_threshold, sorted_trades[:hard_max]


def get_ticker_multiplier(ticker: str, classifications: Dict[str, str], 
                         multipliers: Dict[str, float]) -> float:
    """
    Get the threshold multiplier for a ticker based on its size/liquidity.
    
    Args:
        ticker: Stock ticker symbol
        classifications: Dict mapping tickers to size categories
        multipliers: Dict mapping size categories to multiplier values
        
    Returns:
        Multiplier value (default 1.0 for 'mid')
    """
    size_class = classifications.get(ticker, 'mid')
    return multipliers.get(size_class, 1.0)


# =============================================================================
# TRADE CLASSIFICATION
# =============================================================================

def classify_trade_tier(premium: float, threshold_tiers: List[int], 
                       ticker_multiplier: float = 1.0) -> Dict[str, Any]:
    """
    Classify a trade into a tier based on premium value.
    
    Args:
        premium: Trade premium in USD
        threshold_tiers: List of threshold tiers
        ticker_multiplier: Multiplier for ticker size
        
    Returns:
        Dictionary with tier info (tier, label, emoji)
    """
    # Define tier labels (assuming standard tier structure)
    tier_labels = {
        0: {'tier': 'notable', 'label': 'NOTABLE', 'emoji': '📊'},
        1: {'tier': 'unusual', 'label': 'UNUSUAL', 'emoji': '👀'},
        2: {'tier': 'whale', 'label': 'WHALE', 'emoji': '💰'},
        3: {'tier': 'strong_whale', 'label': 'STRONG WHALE', 'emoji': '🐋'},
        4: {'tier': 'headline', 'label': 'HEADLINE WHALE', 'emoji': '🔥'},
    }
    
    # Find which tier this trade falls into
    adjusted_tiers = [int(t * ticker_multiplier) for t in threshold_tiers]
    
    tier_idx = 0
    for i, threshold in enumerate(adjusted_tiers):
        if premium >= threshold:
            tier_idx = min(i, 4)  # Cap at headline tier
    
    return tier_labels.get(tier_idx, tier_labels[0])


def build_trade_flags(vol_oi_ratio: Optional[float], dte: Optional[int],
                     vol_oi_high: float = 0.20, vol_oi_notable: float = 0.05) -> List[str]:
    """
    Build list of special flags for a trade.
    
    Args:
        vol_oi_ratio: Trade volume as percentage of open interest
        dte: Days to expiration
        vol_oi_high: Threshold for high vol/OI flag
        vol_oi_notable: Threshold for notable vol/OI flag
        
    Returns:
        List of flag strings
    """
    flags = []
    
    # Volume vs OI flags
    if vol_oi_ratio is not None:
        if vol_oi_ratio >= vol_oi_high:
            flags.append(f"high_vol_oi_{vol_oi_ratio:.0%}")
        elif vol_oi_ratio >= vol_oi_notable:
            flags.append(f"notable_vol_oi_{vol_oi_ratio:.0%}")
    
    # DTE flags
    if dte is not None:
        if dte <= 0:
            flags.append("0dte")
        elif dte <= 2:
            flags.append(f"{dte}dte_aggressive")
        elif dte <= 7:
            flags.append(f"{dte}dte_short")
    
    return flags


def get_dte_bucket(dte: Optional[int]) -> str:
    """
    Categorize a trade by days to expiration bucket.
    
    Args:
        dte: Days to expiration
        
    Returns:
        Bucket name string
    """
    if dte is None:
        return "unknown"
    elif dte <= 0:
        return "0dte"
    elif dte <= 2:
        return "1_2_days"
    elif dte <= 7:
        return "3_7_days"
    elif dte <= 30:
        return "8_30_days"
    elif dte <= 90:
        return "31_90_days"
    else:
        return "90_plus"


# =============================================================================
# SWEEP DETECTION
# =============================================================================

def detect_sweeps(trades: List[Dict], time_window_seconds: int = 60, 
                 min_legs: int = 3) -> List[Dict]:
    """
    Detect potential sweep orders from a list of trades.
    
    A sweep is when someone aggressively buys/sells across multiple strikes
    or exchanges in rapid succession, often to fill a large order quickly.
    
    Args:
        trades: List of trade dictionaries with 'timestamp' and 'underlying' keys
        time_window_seconds: Trades within this window may be a sweep
        min_legs: Minimum trades to qualify as a sweep
        
    Returns:
        List of detected sweep dictionaries
    """
    sweeps = []
    sweep_counter = defaultdict(int)
    
    # Group by underlying
    by_underlying = defaultdict(list)
    for trade in trades:
        by_underlying[trade['underlying']].append(trade)
    
    for underlying, ticker_trades in by_underlying.items():
        # Sort by timestamp
        sorted_trades = sorted(ticker_trades, key=lambda x: x.get('timestamp', ''))
        
        i = 0
        while i < len(sorted_trades):
            cluster = [sorted_trades[i]]
            
            # Parse timestamp of first trade
            try:
                t1_str = sorted_trades[i].get('timestamp', '')
                t1 = datetime.fromisoformat(t1_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                i += 1
                continue
            
            # Find all trades within time window
            j = i + 1
            while j < len(sorted_trades):
                try:
                    t2_str = sorted_trades[j].get('timestamp', '')
                    t2 = datetime.fromisoformat(t2_str.replace('Z', '+00:00'))
                    if (t2 - t1).total_seconds() <= time_window_seconds:
                        cluster.append(sorted_trades[j])
                        j += 1
                    else:
                        break
                except (ValueError, TypeError):
                    j += 1
                    break
            
            # Check if cluster qualifies as a sweep
            if len(cluster) >= min_legs:
                sweep_counter[underlying] += 1
                sweep_id = f"{underlying}-sweep-{sweep_counter[underlying]}"
                
                # Calculate totals
                total_premium = sum(t.get('premium', 0) for t in cluster)
                total_contracts = sum(t.get('contracts', 0) for t in cluster)
                strikes = list(set(t.get('strike', 0) for t in cluster))
                types = list(set(t.get('type', '') for t in cluster))
                
                # Determine sweep sentiment
                call_premium = sum(t.get('premium', 0) for t in cluster if t.get('type') == 'CALL')
                put_premium = sum(t.get('premium', 0) for t in cluster if t.get('type') == 'PUT')
                sentiment = 'BULLISH' if call_premium >= put_premium else 'BEARISH'
                
                # Mark individual trades as part of sweep
                for trade in cluster:
                    trade['is_sweep'] = True
                    trade['sweep_id'] = sweep_id
                
                sweeps.append({
                    'sweep_id': sweep_id,
                    'underlying': underlying,
                    'legs': len(cluster),
                    'total_premium': total_premium,
                    'total_contracts': total_contracts,
                    'strikes': sorted(strikes),
                    'types': types,
                    'sentiment': sentiment,
                    'start_time': cluster[0].get('timestamp', ''),
                    'end_time': cluster[-1].get('timestamp', ''),
                    'trade_ids': [t.get('contract', '') for t in cluster]
                })
            
            i = j if j > i + 1 else i + 1
    
    # Sort by total premium
    sweeps.sort(key=lambda x: x['total_premium'], reverse=True)
    return sweeps


# =============================================================================
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Simple rate limiter to prevent exceeding API rate limits.
    
    Usage:
        limiter = RateLimiter(max_requests_per_minute=180)
        
        for ticker in tickers:
            limiter.wait_if_needed()
            api_call()
    """
    
    def __init__(self, max_requests_per_minute: int = 180, 
                 min_delay_seconds: float = 0.35):
        """
        Initialize rate limiter.
        
        Args:
            max_requests_per_minute: Maximum API requests allowed per minute
            min_delay_seconds: Minimum delay between requests
        """
        self.max_rpm = max_requests_per_minute
        self.min_delay = min_delay_seconds
        self.request_times: List[float] = []
        self.last_request_time: float = 0
    
    def wait_if_needed(self):
        """Wait if necessary to stay within rate limits."""
        current_time = time.time()
        
        # Enforce minimum delay between requests
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_delay:
            time.sleep(self.min_delay - time_since_last)
        
        # Clean old request times (older than 1 minute)
        cutoff = current_time - 60
        self.request_times = [t for t in self.request_times if t > cutoff]
        
        # If we're at the limit, wait until oldest request expires
        if len(self.request_times) >= self.max_rpm:
            wait_time = self.request_times[0] + 60 - current_time
            if wait_time > 0:
                print(f"Rate limit reached, waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        # Record this request
        self.last_request_time = time.time()
        self.request_times.append(self.last_request_time)
    
    def get_requests_remaining(self) -> int:
        """Get number of requests remaining in current minute window."""
        current_time = time.time()
        cutoff = current_time - 60
        recent_requests = len([t for t in self.request_times if t > cutoff])
        return max(0, self.max_rpm - recent_requests)


def rate_limited(limiter: RateLimiter):
    """
    Decorator to apply rate limiting to a function.
    
    Args:
        limiter: RateLimiter instance
        
    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait_if_needed()
            return func(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# SENTIMENT CALCULATIONS
# =============================================================================

def calculate_sentiment(trades: List[Dict]) -> Dict[str, Any]:
    """
    Calculate overall sentiment from a list of trades.
    
    Args:
        trades: List of trade dictionaries
        
    Returns:
        Dictionary with sentiment metrics
    """
    calls = [t for t in trades if t.get('type') == 'CALL']
    puts = [t for t in trades if t.get('type') == 'PUT']
    
    call_premium = sum(t.get('premium', 0) for t in calls)
    put_premium = sum(t.get('premium', 0) for t in puts)
    total_premium = call_premium + put_premium
    
    if total_premium == 0:
        return {
            'direction': 'NEUTRAL',
            'call_count': 0,
            'put_count': 0,
            'call_premium': 0,
            'put_premium': 0,
            'call_put_ratio': 0,
            'net_premium': 0
        }
    
    if call_premium > put_premium:
        direction = 'BULLISH'
        ratio = call_premium / put_premium if put_premium > 0 else float('inf')
    elif put_premium > call_premium:
        direction = 'BEARISH'
        ratio = put_premium / call_premium if call_premium > 0 else float('inf')
    else:
        direction = 'NEUTRAL'
        ratio = 1.0
    
    return {
        'direction': direction,
        'call_count': len(calls),
        'put_count': len(puts),
        'call_premium': call_premium,
        'put_premium': put_premium,
        'call_put_ratio': round(ratio, 2) if ratio != float('inf') else None,
        'net_premium': call_premium - put_premium
    }


def calculate_sector_sentiment(
    trades_by_ticker: Dict[str, List[Dict]],
    ticker_to_sector: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict]:
    """
    Calculate sentiment aggregated by sector.
    
    Args:
        trades_by_ticker: Dictionary mapping ticker to list of trades
        ticker_to_sector: Deprecated. Kept for backward compatibility; lookup uses shared.get_sector.
        
    Returns:
        Dictionary mapping sector name to sentiment metrics
    """
    sector_trades = defaultdict(list)
    
    for ticker, trades in trades_by_ticker.items():
        sector = get_sector(ticker)
        sector_trades[sector].extend(trades)
    
    sector_sentiment = {}
    for sector, trades in sector_trades.items():
        sentiment = calculate_sentiment(trades)
        sentiment['ticker_count'] = len(set(t.get('underlying', '') for t in trades))
        sentiment['trade_count'] = len(trades)
        sector_sentiment[sector] = sentiment
    
    return sector_sentiment


def aggregate_by_dte_bucket(trades: List[Dict]) -> Dict[str, Dict]:
    """
    Aggregate trades by days-to-expiration bucket.
    
    Args:
        trades: List of trade dictionaries
        
    Returns:
        Dictionary mapping DTE bucket to aggregate metrics
    """
    buckets = defaultdict(list)
    
    for trade in trades:
        bucket = get_dte_bucket(trade.get('dte'))
        buckets[bucket].append(trade)
    
    result = {}
    for bucket, bucket_trades in buckets.items():
        result[bucket] = {
            'count': len(bucket_trades),
            'premium': sum(t.get('premium', 0) for t in bucket_trades),
            'contracts': sum(t.get('contracts', 0) for t in bucket_trades)
        }
    
    return result


# =============================================================================
# JSON HELPERS
# =============================================================================

def format_currency(value: float) -> str:
    """Format a number as currency string."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.2f}K"
    else:
        return f"${value:.2f}"


def safe_round(value: Optional[float], decimals: int = 2) -> Optional[float]:
    """Safely round a value that might be None."""
    if value is None:
        return None
    return round(value, decimals)
