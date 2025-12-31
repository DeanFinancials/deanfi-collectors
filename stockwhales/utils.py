"""
Stock Whale Collector Utilities

Helper functions for:
- Trading day calculations (using NYSE calendar)
- Dynamic threshold optimization
- Direction inference (Lee-Ready algorithm)
- Rate limiting
- Ticker format conversion
- Trade classification and sentiment
"""

import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from collections import defaultdict

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

# Tickers to skip entirely (no liquid stock or problematic)
SKIP_TICKERS = {
    "BRK.A",  # Berkshire Class A - extremely high price
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
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Simple rate limiter for API calls.
    
    Tracks request timestamps and enforces a maximum requests per minute limit.
    """
    
    def __init__(self, max_per_minute: int = 180):
        """
        Initialize rate limiter.
        
        Args:
            max_per_minute: Maximum requests allowed per minute
        """
        self.max_per_minute = max_per_minute
        self.request_times: List[float] = []
    
    def wait_if_needed(self):
        """
        Wait if we're at the rate limit.
        
        Blocks until it's safe to make another request.
        """
        now = time.time()
        
        # Remove requests older than 60 seconds
        self.request_times = [t for t in self.request_times if now - t < 60]
        
        # If at limit, wait for oldest request to expire
        if len(self.request_times) >= self.max_per_minute:
            oldest = min(self.request_times)
            wait_time = 60 - (now - oldest) + 0.1
            if wait_time > 0:
                print(f"Rate limit reached, waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        # Record this request
        self.request_times.append(time.time())


# =============================================================================
# DIRECTION INFERENCE (LEE-READY ALGORITHM)
# =============================================================================

def infer_trade_direction(trade_price: float, bid: float, ask: float,
                          near_ask_threshold: float = 0.7,
                          near_bid_threshold: float = 0.3) -> Dict[str, Any]:
    """
    Infer trade direction using the Quote Rule (Lee-Ready algorithm simplified).
    
    Compares trade price to the bid/ask spread to determine if the trade
    was likely initiated by a buyer or seller.
    
    Args:
        trade_price: The trade execution price
        bid: The bid price at time of trade
        ask: The ask price at time of trade
        near_ask_threshold: Position in spread to consider "near ask" (default 0.7 = 70%)
        near_bid_threshold: Position in spread to consider "near bid" (default 0.3 = 30%)
    
    Returns:
        dict with 'direction', 'confidence', 'emoji', and 'description'
    """
    if bid is None or ask is None or bid == 0 or ask == 0:
        return {
            'direction': 'UNKNOWN',
            'confidence': 0,
            'emoji': '⚪',
            'description': 'No quote data available'
        }
    
    mid_price = (bid + ask) / 2
    spread = ask - bid
    
    # Handle zero spread (locked market)
    if spread == 0:
        return {
            'direction': 'NEUTRAL',
            'confidence': 50,
            'emoji': '⚪',
            'description': 'Market locked (bid = ask)'
        }
    
    # Calculate where the trade occurred within the spread
    # 0 = at bid, 1 = at ask, 0.5 = at midpoint
    position_in_spread = (trade_price - bid) / spread
    
    # Clamp to handle trades outside the spread
    position_in_spread = max(0, min(1, position_in_spread))
    
    if trade_price >= ask:
        # Trade at or above ask - strong buy signal
        return {
            'direction': 'BUY',
            'confidence': 95,
            'emoji': '🟢',
            'description': 'Trade AT/ABOVE ASK - Aggressive BUY (buyer lifted offer)'
        }
    elif trade_price <= bid:
        # Trade at or below bid - strong sell signal
        return {
            'direction': 'SELL',
            'confidence': 95,
            'emoji': '🔴',
            'description': 'Trade AT/BELOW BID - Aggressive SELL (seller hit bid)'
        }
    elif position_in_spread >= near_ask_threshold:
        # Trade closer to ask
        confidence = int(50 + (position_in_spread - 0.5) * 90)
        return {
            'direction': 'BUY',
            'confidence': confidence,
            'emoji': '🟢',
            'description': f'Trade near ASK ({position_in_spread:.0%} of spread) - Likely BUY'
        }
    elif position_in_spread <= near_bid_threshold:
        # Trade closer to bid
        confidence = int(50 + (0.5 - position_in_spread) * 90)
        return {
            'direction': 'SELL',
            'confidence': confidence,
            'emoji': '🔴',
            'description': f'Trade near BID ({position_in_spread:.0%} of spread) - Likely SELL'
        }
    else:
        # Trade near midpoint - uncertain
        return {
            'direction': 'NEUTRAL',
            'confidence': 50,
            'emoji': '⚪',
            'description': f'Trade at MIDPOINT ({position_in_spread:.0%} of spread) - Direction unclear'
        }


# =============================================================================
# THRESHOLD AND TIER UTILITIES
# =============================================================================

def is_whale_trade(shares: int, value: float, 
                   min_shares: int, min_value: float,
                   multiplier: float = 1.0) -> bool:
    """
    Check if a trade qualifies as a whale trade.
    
    Trade qualifies if it meets EITHER threshold (OR logic).
    
    Args:
        shares: Number of shares in the trade
        value: Dollar value of the trade
        min_shares: Minimum share threshold
        min_value: Minimum value threshold
        multiplier: Ticker-size multiplier (e.g., 2.0 for mega caps)
        
    Returns:
        True if trade qualifies as whale
    """
    adjusted_shares = min_shares * multiplier
    adjusted_value = min_value * multiplier
    
    return shares >= adjusted_shares or value >= adjusted_value


def find_optimal_threshold(trades: List[Dict], tiers: List[Dict],
                          target_min: int, target_max: int,
                          hard_max: int, multiplier: float = 1.0) -> Tuple[Dict, List[Dict]]:
    """
    Find the optimal threshold tier for a ticker's trades.
    
    Starts at the lowest tier and steps up until we have <= target_max trades.
    Never returns more than hard_max trades.
    
    Args:
        trades: List of trade dictionaries with 'shares' and 'value'
        tiers: List of tier dictionaries with 'shares' and 'value' thresholds
        target_min: Target minimum trades
        target_max: Target maximum trades
        hard_max: Absolute maximum trades to return
        multiplier: Ticker-size multiplier
        
    Returns:
        Tuple of (effective_tier, filtered_trades)
    """
    effective_tier = tiers[0]  # Start with lowest threshold
    filtered_trades = trades
    
    for tier in tiers:
        adjusted_shares = tier['shares'] * multiplier
        adjusted_value = tier['value'] * multiplier
        
        # Filter trades that meet this tier's threshold
        tier_trades = [
            t for t in trades
            if t.get('shares', 0) >= adjusted_shares or t.get('value', 0) >= adjusted_value
        ]
        
        # If we have <= target_max trades, this tier works
        if len(tier_trades) <= target_max:
            effective_tier = tier
            filtered_trades = tier_trades
            break
        
        # Otherwise, try the next tier
        effective_tier = tier
        filtered_trades = tier_trades
    
    # Apply hard max cap
    if len(filtered_trades) > hard_max:
        # Sort by value descending and take top hard_max
        filtered_trades = sorted(filtered_trades, key=lambda x: x.get('value', 0), reverse=True)[:hard_max]
    
    return effective_tier, filtered_trades


def get_ticker_multiplier(ticker: str, classifications: Dict[str, str],
                         multipliers: Dict[str, float]) -> float:
    """
    Get the threshold multiplier for a ticker based on its classification.
    
    Args:
        ticker: Stock ticker symbol
        classifications: Dict mapping ticker to size class
        multipliers: Dict mapping size class to multiplier
        
    Returns:
        Multiplier value (default 1.0 for 'mid')
    """
    size_class = classifications.get(ticker, 'mid')
    return multipliers.get(size_class, 1.0)


def classify_trade_tier(value: float, tier_labels: Dict[str, Dict]) -> Dict[str, str]:
    """
    Classify a trade into a tier based on its dollar value.
    
    Args:
        value: Dollar value of the trade
        tier_labels: Dictionary of tier definitions from config
        
    Returns:
        Dict with 'tier', 'label', and 'emoji'
    """
    # Sort tiers by min_value ascending
    sorted_tiers = sorted(
        tier_labels.items(),
        key=lambda x: x[1].get('min_value', 0)
    )
    
    for tier_name, tier_info in reversed(sorted_tiers):
        min_val = tier_info.get('min_value', 0)
        max_val = tier_info.get('max_value')
        
        if value >= min_val:
            if max_val is None or value < max_val:
                return {
                    'tier': tier_name,
                    'label': tier_info.get('label', tier_name),
                    'emoji': tier_info.get('emoji', '📊')
                }
    
    # Default to first tier if nothing matched
    first_tier = sorted_tiers[0]
    return {
        'tier': first_tier[0],
        'label': first_tier[1].get('label', first_tier[0]),
        'emoji': first_tier[1].get('emoji', '📊')
    }


# =============================================================================
# SENTIMENT CALCULATIONS
# =============================================================================

def calculate_sentiment(trades: List[Dict], high_confidence_threshold: int = 80) -> Dict[str, Any]:
    """
    Calculate overall sentiment from a list of trades.
    
    Args:
        trades: List of trade dictionaries
        high_confidence_threshold: Minimum confidence for high-confidence trades
        
    Returns:
        Dictionary with sentiment statistics
    """
    if not trades:
        return {
            'direction': 'NEUTRAL',
            'buy_count': 0,
            'sell_count': 0,
            'neutral_count': 0,
            'buy_value': 0,
            'sell_value': 0,
            'net_value': 0,
            'buy_sell_ratio': 0,
            'high_confidence_direction': 'NEUTRAL',
            'hc_buy_count': 0,
            'hc_sell_count': 0,
            'hc_buy_value': 0,
            'hc_sell_value': 0,
            'hc_net_value': 0
        }
    
    # Count and sum by direction
    buys = [t for t in trades if t.get('direction') == 'BUY']
    sells = [t for t in trades if t.get('direction') == 'SELL']
    neutrals = [t for t in trades if t.get('direction') in ('NEUTRAL', 'UNKNOWN')]
    
    buy_value = sum(t.get('value', 0) for t in buys)
    sell_value = sum(t.get('value', 0) for t in sells)
    net_value = buy_value - sell_value
    
    # High confidence trades
    hc_buys = [t for t in buys if t.get('direction_confidence', 0) >= high_confidence_threshold]
    hc_sells = [t for t in sells if t.get('direction_confidence', 0) >= high_confidence_threshold]
    hc_buy_value = sum(t.get('value', 0) for t in hc_buys)
    hc_sell_value = sum(t.get('value', 0) for t in hc_sells)
    hc_net_value = hc_buy_value - hc_sell_value
    
    # Determine overall direction
    if net_value > 0:
        direction = 'BULLISH'
    elif net_value < 0:
        direction = 'BEARISH'
    else:
        direction = 'NEUTRAL'
    
    # Determine high-confidence direction
    if hc_net_value > 0:
        hc_direction = 'BULLISH'
    elif hc_net_value < 0:
        hc_direction = 'BEARISH'
    else:
        hc_direction = 'NEUTRAL'
    
    # Buy/Sell ratio
    buy_sell_ratio = round(buy_value / sell_value, 2) if sell_value > 0 else (float('inf') if buy_value > 0 else 0)
    
    return {
        'direction': direction,
        'buy_count': len(buys),
        'sell_count': len(sells),
        'neutral_count': len(neutrals),
        'buy_value': buy_value,
        'sell_value': sell_value,
        'net_value': net_value,
        'buy_sell_ratio': buy_sell_ratio if buy_sell_ratio != float('inf') else 999.99,
        'high_confidence_direction': hc_direction,
        'hc_buy_count': len(hc_buys),
        'hc_sell_count': len(hc_sells),
        'hc_buy_value': hc_buy_value,
        'hc_sell_value': hc_sell_value,
        'hc_net_value': hc_net_value
    }


def calculate_dark_pool_sentiment(trades: List[Dict], high_confidence_threshold: int = 80) -> Dict[str, Any]:
    """
    Calculate sentiment specifically for dark pool trades.
    
    Args:
        trades: List of trade dictionaries (should be dark pool trades only)
        high_confidence_threshold: Minimum confidence for high-confidence trades
        
    Returns:
        Dictionary with dark pool sentiment statistics
    """
    sentiment = calculate_sentiment(trades, high_confidence_threshold)
    
    # Add dark pool specific context
    total_value = sentiment['buy_value'] + sentiment['sell_value']
    
    return {
        **sentiment,
        'total_trades': len(trades),
        'total_value': total_value,
        'context': 'Dark pool trades execute off-exchange to minimize market impact. These are typically institutional block trades.'
    }


def calculate_sector_sentiment(
    trades_by_ticker: Dict[str, List[Dict]],
    ticker_to_sector: Optional[Dict[str, str]] = None,
    high_confidence_threshold: int = 80,
) -> Dict[str, Dict]:
    """
    Calculate sentiment aggregated by sector.
    
    Args:
        trades_by_ticker: Dictionary mapping ticker to list of trades
        ticker_to_sector: Deprecated. Kept for backward compatibility; lookup uses shared.get_sector.
        high_confidence_threshold: Minimum confidence for high-confidence trades
        
    Returns:
        Dictionary mapping sector to sentiment statistics
    """
    sector_trades = defaultdict(list)
    
    for ticker, trades in trades_by_ticker.items():
        sector = get_sector(ticker)
        sector_trades[sector].extend(trades)
    
    sector_sentiment = {}
    for sector, trades in sector_trades.items():
        sentiment = calculate_sentiment(trades, high_confidence_threshold)
        sector_sentiment[sector] = {
            **sentiment,
            'ticker_count': len(set(t.get('ticker', '') for t in trades)),
            'trade_count': len(trades)
        }
    
    return sector_sentiment


# =============================================================================
# FORMATTING UTILITIES
# =============================================================================

def format_currency(value: float) -> str:
    """Format a number as currency string (e.g., $1.5M)."""
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"${value/1_000:.1f}K"
    else:
        return f"${value:.0f}"


def format_shares(shares: int) -> str:
    """Format share count (e.g., 10K shares)."""
    if shares >= 1_000_000:
        return f"{shares/1_000_000:.1f}M"
    elif shares >= 1_000:
        return f"{shares/1_000:.1f}K"
    else:
        return str(shares)


def safe_round(value: Any, decimals: int = 2) -> Any:
    """Safely round a value, returning None if not numeric."""
    if value is None:
        return None
    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return None
