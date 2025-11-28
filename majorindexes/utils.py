"""
Utility functions for major indices data processing and technical analysis.

Provides:
- Technical indicators: SMA, RSI, MACD, Bollinger Bands
- Date/time utilities: Trading days, market hours detection
- Data formatting: JSON serialization, number formatting
- Performance metrics: Returns, volatility, Sharpe ratio, drawdowns
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz
from typing import Dict, List, Optional, Tuple
import json


# ==============================================================================
# TECHNICAL INDICATORS
# ==============================================================================

def calculate_sma(prices: pd.Series, periods: List[int] = [20, 50, 200]) -> Dict[str, float]:
    """
    Calculate Simple Moving Averages for given periods.
    
    Args:
        prices: Series of closing prices (newest first or oldest first)
        periods: List of SMA periods to calculate (default: [20, 50, 200])
    
    Returns:
        Dict with keys like 'sma_20', 'sma_50', 'sma_200'
    """
    result = {}
    for period in periods:
        if len(prices) >= period:
            sma = prices.tail(period).mean()
            result[f'sma_{period}'] = round(float(sma), 2)
        else:
            result[f'sma_{period}'] = None
    return result


def calculate_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """
    Calculate Relative Strength Index (RSI).
    
    Args:
        prices: Series of closing prices
        period: RSI period (default: 14)
    
    Returns:
        RSI value between 0-100, or None if insufficient data
    """
    if len(prices) < period + 1:
        return None
    
    # Calculate price changes
    delta = prices.diff()
    
    # Separate gains and losses
    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)
    
    # Calculate average gains and losses
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()
    
    # Calculate RS and RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # Return most recent RSI value
    return round(float(rsi.iloc[-1]), 2)


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    Args:
        prices: Series of closing prices
        fast: Fast EMA period (default: 12)
        slow: Slow EMA period (default: 26)
        signal: Signal line EMA period (default: 9)
    
    Returns:
        Dict with 'macd_line', 'signal_line', 'histogram'
    """
    if len(prices) < slow + signal:
        return {'macd_line': None, 'signal_line': None, 'histogram': None}
    
    # Calculate EMAs
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    
    # MACD line
    macd_line = ema_fast - ema_slow
    
    # Signal line
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    
    # Histogram
    histogram = macd_line - signal_line
    
    return {
        'macd_line': round(float(macd_line.iloc[-1]), 2),
        'signal_line': round(float(signal_line.iloc[-1]), 2),
        'histogram': round(float(histogram.iloc[-1]), 2)
    }


def calculate_bollinger_bands(prices: pd.Series, period: int = 20, std_dev: int = 2) -> Dict[str, float]:
    """
    Calculate Bollinger Bands.
    
    Args:
        prices: Series of closing prices
        period: SMA period (default: 20)
        std_dev: Number of standard deviations (default: 2)
    
    Returns:
        Dict with 'upper', 'middle', 'lower' bands
    """
    if len(prices) < period:
        return {'upper': None, 'middle': None, 'lower': None}
    
    # Middle band (SMA)
    middle = prices.tail(period).mean()
    
    # Standard deviation
    std = prices.tail(period).std()
    
    # Upper and lower bands
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    
    return {
        'upper': round(float(upper), 2),
        'middle': round(float(middle), 2),
        'lower': round(float(lower), 2)
    }


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """
    Calculate pivot points for support and resistance levels.
    Uses previous day's High, Low, Close.
    
    Formula:
        Pivot Point (PP) = (H + L + C) / 3
        R1 = (2 × PP) - L
        R2 = PP + (H - L)
        R3 = H + (2 × (PP - L))
        S1 = (2 × PP) - H
        S2 = PP - (H - L)
        S3 = L - (2 × (H - L))
    
    Args:
        high: Previous day's high
        low: Previous day's low
        close: Previous day's close
    
    Returns:
        Dict with pivot_point, resistance levels (r1, r2, r3), support levels (s1, s2, s3)
    """
    # Pivot Point
    pp = (high + low + close) / 3
    
    # Resistance levels
    r1 = (2 * pp) - low
    r2 = pp + (high - low)
    r3 = high + (2 * (pp - low))
    
    # Support levels
    s1 = (2 * pp) - high
    s2 = pp - (high - low)
    s3 = low - (2 * (high - low))
    
    return {
        'pivot_point': round(pp, 2),
        'resistance_1': round(r1, 2),
        'resistance_2': round(r2, 2),
        'resistance_3': round(r3, 2),
        'support_1': round(s1, 2),
        'support_2': round(s2, 2),
        'support_3': round(s3, 2)
    }


def calculate_all_technical_indicators(prices: pd.Series) -> Dict:
    """
    Calculate all technical indicators in one go.
    
    Args:
        prices: Series of closing prices (oldest to newest)
    
    Returns:
        Dict with all technical indicators
    """
    return {
        'moving_averages': calculate_sma(prices, [20, 50, 200]),
        'rsi_14': calculate_rsi(prices, 14),
        'macd': calculate_macd(prices),
        'bollinger_bands': calculate_bollinger_bands(prices)
    }


# ==============================================================================
# PERFORMANCE METRICS
# ==============================================================================

def calculate_returns(prices: pd.Series) -> Dict[str, float]:
    """
    Calculate various period returns.
    
    Args:
        prices: Series of closing prices (oldest to newest)
    
    Returns:
        Dict with returns for different periods
    """
    if len(prices) < 2:
        return {}
    
    current_price = prices.iloc[-1]
    returns = {}
    
    # Year-to-date return
    year_start = pd.Timestamp(datetime(datetime.now().year, 1, 1))
    # Make timezone-naive for comparison
    prices_index = prices.index.tz_localize(None) if hasattr(prices.index, 'tz') and prices.index.tz else prices.index
    ytd_prices = prices[prices_index >= year_start]
    if len(ytd_prices) > 1:
        ytd_return = ((current_price - ytd_prices.iloc[0]) / ytd_prices.iloc[0]) * 100
        returns['year_to_date_percent'] = round(float(ytd_return), 2)
    
    # Period returns
    periods = {
        '1_month_percent': 21,
        '3_month_percent': 63,
        '6_month_percent': 126,
        '1_year_percent': 252
    }
    
    for key, days in periods.items():
        if len(prices) > days:
            past_price = prices.iloc[-days-1]
            period_return = ((current_price - past_price) / past_price) * 100
            returns[key] = round(float(period_return), 2)
    
    return returns


def calculate_52_week_metrics(prices: pd.Series) -> Dict[str, float]:
    """
    Calculate 52-week high/low and distance from high.
    
    Args:
        prices: Series of closing prices (last 252 days)
    
    Returns:
        Dict with 52-week metrics
    """
    if len(prices) < 2:
        return {}
    
    current_price = prices.iloc[-1]
    week_52_high = prices.max()
    week_52_low = prices.min()
    
    distance_from_high = ((current_price - week_52_high) / week_52_high) * 100
    
    return {
        '52_week_high': round(float(week_52_high), 2),
        '52_week_low': round(float(week_52_low), 2),
        'distance_from_52w_high_percent': round(float(distance_from_high), 2)
    }


def calculate_volatility(returns: pd.Series, annualize: bool = True) -> float:
    """
    Calculate volatility (standard deviation of returns).
    
    Args:
        returns: Series of daily returns (as percentages or decimals)
        annualize: Whether to annualize the volatility
    
    Returns:
        Annualized volatility percentage
    """
    if len(returns) < 2:
        return None
    
    vol = returns.std()
    
    if annualize:
        vol = vol * np.sqrt(252)  # Annualize with 252 trading days
    
    return round(float(vol), 2)


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.04) -> float:
    """
    Calculate Sharpe Ratio (risk-adjusted return).
    
    Args:
        returns: Series of daily returns (as decimals, not percentages)
        risk_free_rate: Annual risk-free rate (default: 4%)
    
    Returns:
        Sharpe ratio
    """
    if len(returns) < 2:
        return None
    
    # Annualized return
    mean_return = returns.mean() * 252
    
    # Annualized volatility
    volatility = returns.std() * np.sqrt(252)
    
    if volatility == 0:
        return None
    
    # Sharpe ratio
    sharpe = (mean_return - risk_free_rate) / volatility
    
    return round(float(sharpe), 2)


def calculate_max_drawdown(prices: pd.Series) -> float:
    """
    Calculate maximum drawdown (largest peak-to-trough decline).
    
    Args:
        prices: Series of closing prices
    
    Returns:
        Maximum drawdown as negative percentage
    """
    if len(prices) < 2:
        return None
    
    # Calculate running maximum
    running_max = prices.expanding().max()
    
    # Calculate drawdown at each point
    drawdown = (prices - running_max) / running_max * 100
    
    # Maximum drawdown (most negative value)
    max_dd = drawdown.min()
    
    return round(float(max_dd), 2)


def calculate_statistics(prices: pd.Series) -> Dict:
    """
    Calculate comprehensive statistics for historical data.
    
    Args:
        prices: Series of closing prices
    
    Returns:
        Dict with statistical metrics
    """
    if len(prices) < 2:
        return {}
    
    # Calculate daily returns
    returns = prices.pct_change().dropna()
    
    # Count up/down days
    days_up = (returns > 0).sum()
    days_down = (returns < 0).sum()
    total_days = len(returns)
    
    # Period return
    period_return = ((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0]) * 100
    
    stats = {
        'period_return_percent': round(float(period_return), 2),
        'volatility_annual_percent': calculate_volatility(returns, annualize=True),
        'max_drawdown_percent': calculate_max_drawdown(prices),
        'sharpe_ratio': calculate_sharpe_ratio(returns),
        'average_daily_volume': None,  # Will be filled by caller if volume data available
        'days_up': int(days_up),
        'days_down': int(days_down),
        'win_rate_percent': round((days_up / total_days) * 100, 2) if total_days > 0 else None
    }
    
    return stats


# ==============================================================================
# DATE/TIME UTILITIES
# ==============================================================================

def get_market_hours_status() -> str:
    """
    Determine current market hours status.
    
    Returns:
        'pre' | 'during' | 'post' | 'closed'
    """
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    # Weekend check
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return 'closed'
    
    current_time = now.time()
    
    # Market hours (9:30 AM - 4:00 PM ET)
    market_open = time(9, 30)
    market_close = time(16, 0)
    
    # Pre-market (4:00 AM - 9:30 AM)
    pre_market_open = time(4, 0)
    
    # After-hours (4:00 PM - 8:00 PM)
    after_hours_close = time(20, 0)
    
    if pre_market_open <= current_time < market_open:
        return 'pre'
    elif market_open <= current_time < market_close:
        return 'during'
    elif market_close <= current_time < after_hours_close:
        return 'post'
    else:
        return 'closed'


def get_trading_days_count(start_date: datetime, end_date: datetime) -> int:
    """
    Calculate number of trading days between two dates.
    Approximation: excludes weekends, doesn't account for holidays.
    
    Args:
        start_date: Start date
        end_date: End date
    
    Returns:
        Approximate number of trading days
    """
    # Generate business day range
    business_days = pd.bdate_range(start=start_date, end=end_date)
    return len(business_days)


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """
    Format datetime as ISO 8601 string with timezone.
    
    Args:
        dt: Datetime object (uses current time if None)
    
    Returns:
        ISO 8601 formatted string (e.g., '2025-11-16T16:30:00Z')
    """
    if dt is None:
        dt = datetime.utcnow()
    
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def format_date(dt: Optional[datetime] = None) -> str:
    """
    Format datetime as date string.
    
    Args:
        dt: Datetime object (uses current date if None)
    
    Returns:
        Date string (e.g., '2025-11-16')
    """
    if dt is None:
        dt = datetime.now()
    
    return dt.strftime('%Y-%m-%d')


# ==============================================================================
# DATA FORMATTING & VALIDATION
# ==============================================================================

def safe_round(value: any, decimals: int = 2) -> Optional[float]:
    """
    Safely round a value, handling None and non-numeric values.
    
    Args:
        value: Value to round
        decimals: Number of decimal places
    
    Returns:
        Rounded float or None
    """
    if value is None or pd.isna(value):
        return None
    
    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return None


def format_large_number(value: float, decimals: int = 2) -> Optional[float]:
    """
    Format large numbers (volume, market cap) with appropriate precision.
    
    Args:
        value: Number to format
        decimals: Decimal places
    
    Returns:
        Formatted number
    """
    return safe_round(value, decimals)


def calculate_data_quality(data_points: int, expected_points: int = 252, 
                          last_update: Optional[datetime] = None) -> Dict:
    """
    Calculate data quality metrics.
    
    Args:
        data_points: Number of data points received
        expected_points: Expected number of points (default: 252)
        last_update: Timestamp of last update
    
    Returns:
        Dict with quality metrics
    """
    missing_days = max(0, expected_points - data_points)
    completeness = (data_points / expected_points) * 100 if expected_points > 0 else 0
    
    # Determine status
    if completeness >= 95:
        status = 'complete'
    elif completeness >= 80:
        status = 'partial'
    else:
        status = 'stale'
    
    quality = {
        'status': status,
        'missing_days': missing_days,
        'completeness_percent': round(completeness, 1),
        'last_update': format_timestamp(last_update),
        'market_hours': get_market_hours_status()
    }
    
    return quality


def create_index_metadata(symbol: str, name: str, data_count: int, 
                         indices_total: int = 1) -> Dict:
    """
    Create standard metadata section for JSON output.
    
    Args:
        symbol: Index symbol
        name: Index name
        data_count: Number of data points
        indices_total: Total number of indices in file
    
    Returns:
        Metadata dict
    """
    return {
        'generated_at': format_timestamp(),
        'market_date': format_date(),
        'market_status': get_market_hours_status(),
        'indices_count': indices_total,
        'data_source': 'Yahoo Finance (yfinance)',
        'data_quality': calculate_data_quality(data_count, 252)
    }


# ==============================================================================
# JSON SERIALIZATION
# ==============================================================================

class NumpyEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle NumPy types.
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        return super(NumpyEncoder, self).default(obj)


def save_json(data: Dict, filepath: str, indent: int = 2):
    """
    Save data to JSON file with pretty formatting.
    
    Args:
        data: Dictionary to save
        filepath: Output file path
        indent: JSON indentation (default: 2)
    """
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=indent, cls=NumpyEncoder)


def load_json(filepath: str) -> Dict:
    """
    Load JSON file.
    
    Args:
        filepath: JSON file path
    
    Returns:
        Loaded dictionary
    """
    with open(filepath, 'r') as f:
        return json.load(f)


# ==============================================================================
# DATA TRANSFORMATION
# ==============================================================================

def dataframe_to_daily_records(df: pd.DataFrame) -> List[Dict]:
    """
    Convert DataFrame to list of daily records for JSON output.
    
    Args:
        df: DataFrame with OHLCV data (index = dates)
    
    Returns:
        List of dicts with daily data
    """
    records = []
    
    for date, row in df.iterrows():
        # Calculate daily return
        daily_return = None
        if len(records) > 0:
            prev_close = records[-1]['close']
            if prev_close and prev_close != 0:
                daily_return = ((row['Close'] - prev_close) / prev_close) * 100
        
        record = {
            'date': date.strftime('%Y-%m-%d'),
            'open': safe_round(row['Open'], 2),
            'high': safe_round(row['High'], 2),
            'low': safe_round(row['Low'], 2),
            'close': safe_round(row['Close'], 2),
            'volume': int(row['Volume']) if not pd.isna(row['Volume']) else None,
            'daily_return_percent': safe_round(daily_return, 2)
        }
        records.append(record)
    
    return records


def get_current_snapshot(df: pd.DataFrame) -> Dict:
    """
    Extract current day snapshot from DataFrame.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        Dict with current day metrics
    """
    if len(df) == 0:
        return {}
    
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest
    
    current_price = safe_round(latest['Close'], 2)
    previous_close = safe_round(previous['Close'], 2)
    
    # Daily change
    daily_change = safe_round(current_price - previous_close, 2) if current_price and previous_close else None
    daily_change_percent = safe_round(((current_price - previous_close) / previous_close) * 100, 2) if current_price and previous_close and previous_close != 0 else None
    
    snapshot = {
        'current_price': current_price,
        'daily_change': daily_change,
        'daily_change_percent': daily_change_percent,
        'volume': int(latest['Volume']) if not pd.isna(latest['Volume']) else None,
        'day_high': safe_round(latest['High'], 2),
        'day_low': safe_round(latest['Low'], 2),
        'day_open': safe_round(latest['Open'], 2)
    }
    
    return snapshot


def get_current_snapshot_from_info(ticker_info: Dict, df: pd.DataFrame = None) -> Dict:
    """
    Extract current day snapshot from yfinance ticker.info.
    
    This is more reliable than historical data for futures/commodities because
    ticker.info provides the actual previous close and daily change from Yahoo,
    avoiding issues with gaps in historical data around holidays.
    
    Args:
        ticker_info: Dict from yfinance Ticker.info
        df: Optional DataFrame for fallback OHLCV data (high, low, open, volume)
    
    Returns:
        Dict with current day metrics
    """
    current_price = safe_round(ticker_info.get('regularMarketPrice'), 2)
    previous_close = safe_round(ticker_info.get('regularMarketPreviousClose'), 2)
    
    # Use Yahoo's calculated daily change (more reliable for futures with gaps)
    daily_change = safe_round(ticker_info.get('regularMarketChange'), 2)
    daily_change_percent = safe_round(ticker_info.get('regularMarketChangePercent'), 2)
    
    # Get intraday data from ticker.info
    day_high = safe_round(ticker_info.get('regularMarketDayHigh') or ticker_info.get('dayHigh'), 2)
    day_low = safe_round(ticker_info.get('regularMarketDayLow') or ticker_info.get('dayLow'), 2)
    day_open = safe_round(ticker_info.get('regularMarketOpen') or ticker_info.get('open'), 2)
    volume = ticker_info.get('regularMarketVolume') or ticker_info.get('volume')
    
    # If info doesn't have OHLV, fall back to DataFrame
    if df is not None and len(df) > 0:
        latest = df.iloc[-1]
        if day_high is None:
            day_high = safe_round(latest.get('High'), 2)
        if day_low is None:
            day_low = safe_round(latest.get('Low'), 2)
        if day_open is None:
            day_open = safe_round(latest.get('Open'), 2)
        if volume is None and 'Volume' in latest:
            volume = int(latest['Volume']) if not pd.isna(latest['Volume']) else None
    
    snapshot = {
        'current_price': current_price,
        'daily_change': daily_change,
        'daily_change_percent': daily_change_percent,
        'volume': int(volume) if volume and not pd.isna(volume) else None,
        'day_high': day_high,
        'day_low': day_low,
        'day_open': day_open
    }
    
    return snapshot


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def determine_market_sentiment(positive_count: int, total_count: int) -> str:
    """
    Determine market sentiment based on positive/negative ratio.
    
    Args:
        positive_count: Number of positive indices
        total_count: Total number of indices
    
    Returns:
        'bullish' | 'neutral' | 'bearish'
    """
    if total_count == 0:
        return 'neutral'
    
    positive_ratio = positive_count / total_count
    
    if positive_ratio >= 0.6:
        return 'bullish'
    elif positive_ratio <= 0.4:
        return 'bearish'
    else:
        return 'neutral'


def rank_by_performance(indices_data: Dict[str, Dict], metric: str = 'daily_change_percent') -> List[Tuple[str, float]]:
    """
    Rank indices by performance metric.
    
    Args:
        indices_data: Dict of index symbol -> data
        metric: Metric to rank by (default: 'daily_change_percent')
    
    Returns:
        List of (symbol, value) tuples sorted by performance
    """
    performances = []
    
    for symbol, data in indices_data.items():
        value = data.get(metric)
        if value is not None:
            performances.append((symbol, value))
    
    # Sort by value descending
    performances.sort(key=lambda x: x[1], reverse=True)
    
    return performances
