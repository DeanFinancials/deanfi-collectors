"""
Mean Reversion Utility Functions

Provides comprehensive calculations for mean reversion analysis:
- Price vs MA: Distance, percent deviation, z-score
- MA Spreads: Spread, percent spread, z-score
- Statistical helpers: Rolling mean, standard deviation, z-scores
- Data formatting: JSON serialization, metadata generation

Author: DeanFinancials
License: MIT
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import json


# ==============================================================================
# MOVING AVERAGE CALCULATIONS
# ==============================================================================

def calculate_sma(prices: pd.Series, period: int) -> pd.Series:
    """
    Calculate Simple Moving Average.
    
    Args:
        prices: Series of closing prices
        period: Number of periods for SMA
    
    Returns:
        Series with SMA values (NaN for insufficient data)
    """
    return prices.rolling(window=period, min_periods=period).mean()


def calculate_all_mas(prices: pd.Series, periods: List[int] = [20, 50, 200]) -> Dict[str, pd.Series]:
    """
    Calculate multiple SMAs at once.
    
    Args:
        prices: Series of closing prices
        periods: List of MA periods (default: [20, 50, 200])
    
    Returns:
        Dict with keys like 'ma_20', 'ma_50', 'ma_200'
    """
    mas = {}
    for period in periods:
        mas[f'ma_{period}'] = calculate_sma(prices, period)
    return mas


# ==============================================================================
# PRICE VS MA CALCULATIONS
# ==============================================================================

def calculate_price_distance(price: pd.Series, ma: pd.Series) -> pd.Series:
    """
    Calculate simple point distance between price and MA.
    
    Formula: current_price - ma_value
    
    Args:
        price: Series of current prices
        ma: Series of moving average values
    
    Returns:
        Series of distances (positive = above MA, negative = below MA)
    """
    return price - ma


def calculate_price_distance_percent(price: pd.Series, ma: pd.Series) -> pd.Series:
    """
    Calculate percentage distance from MA.
    
    Formula: (current_price - ma_value) / ma_value * 100
    
    Args:
        price: Series of current prices
        ma: Series of moving average values
    
    Returns:
        Series of percent distances
    
    Interpretation:
        >5%: Significantly overbought
        <-5%: Significantly oversold
    """
    return ((price - ma) / ma) * 100


def calculate_price_zscore(price: pd.Series, ma: pd.Series, lookback: int = 252) -> pd.Series:
    """
    Calculate z-score of price distance from MA.
    
    Formula: (current_distance - mean_distance) / std_dev(distance)
    
    Args:
        price: Series of current prices
        ma: Series of moving average values
        lookback: Number of periods for mean/std calculation (default: 252 = 1 year)
    
    Returns:
        Series of z-scores
    
    Interpretation:
        >2: Statistically overbought (>95th percentile)
        <-2: Statistically oversold (<5th percentile)
        -1 to 1: Normal range
    """
    distance = price - ma
    rolling_mean = distance.rolling(window=lookback, min_periods=lookback).mean()
    rolling_std = distance.rolling(window=lookback, min_periods=lookback).std()
    
    # Avoid division by zero
    zscore = (distance - rolling_mean) / rolling_std
    return zscore


def calculate_all_price_vs_ma_metrics(
    price: pd.Series,
    ma: pd.Series,
    ma_period: int,
    lookback: int = 252
) -> pd.DataFrame:
    """
    Calculate all price vs MA metrics at once.
    
    Args:
        price: Series of prices
        ma: Series of MA values
        ma_period: MA period (for column naming)
        lookback: Z-score lookback period
    
    Returns:
        DataFrame with columns:
        - distance: Point distance
        - distance_percent: Percentage distance
        - zscore: Statistical z-score
    """
    df = pd.DataFrame(index=price.index)
    df['distance'] = calculate_price_distance(price, ma)
    df['distance_percent'] = calculate_price_distance_percent(price, ma)
    df['zscore'] = calculate_price_zscore(price, ma, lookback)
    
    return df


# ==============================================================================
# MA SPREAD CALCULATIONS
# ==============================================================================

def calculate_ma_spread(ma_short: pd.Series, ma_long: pd.Series) -> pd.Series:
    """
    Calculate point spread between two moving averages.
    
    Formula: ma_short - ma_long
    
    Args:
        ma_short: Shorter period MA (e.g., 20-day)
        ma_long: Longer period MA (e.g., 50-day)
    
    Returns:
        Series of spreads (positive = bullish, negative = bearish)
    """
    return ma_short - ma_long


def calculate_ma_spread_percent(ma_short: pd.Series, ma_long: pd.Series) -> pd.Series:
    """
    Calculate percentage spread between two MAs.
    
    Formula: (ma_short - ma_long) / ma_long * 100
    
    Args:
        ma_short: Shorter period MA
        ma_long: Longer period MA
    
    Returns:
        Series of percent spreads
    
    Usage: Compare signals across different instruments
    """
    return ((ma_short - ma_long) / ma_long) * 100


def calculate_ma_spread_zscore(
    ma_short: pd.Series,
    ma_long: pd.Series,
    lookback: int = 252
) -> pd.Series:
    """
    Calculate z-score of MA spread.
    
    Formula: (current_spread - mean_spread) / std_dev(spread)
    
    Args:
        ma_short: Shorter period MA
        ma_long: Longer period MA
        lookback: Number of periods for mean/std calculation (default: 252)
    
    Returns:
        Series of z-scores
    
    Interpretation:
        >2: Extremely wide spread (mean reversion likely)
        <-2: Extremely narrow/negative spread
    
    Note: This is the most common institutional method
    """
    spread = ma_short - ma_long
    rolling_mean = spread.rolling(window=lookback, min_periods=lookback).mean()
    rolling_std = spread.rolling(window=lookback, min_periods=lookback).std()
    
    # Avoid division by zero
    zscore = (spread - rolling_mean) / rolling_std
    return zscore


def calculate_all_ma_spread_metrics(
    ma_short: pd.Series,
    ma_long: pd.Series,
    short_period: int,
    long_period: int,
    lookback: int = 252
) -> pd.DataFrame:
    """
    Calculate all MA spread metrics at once.
    
    Args:
        ma_short: Shorter period MA
        ma_long: Longer period MA
        short_period: Short MA period (for naming)
        long_period: Long MA period (for naming)
        lookback: Z-score lookback period
    
    Returns:
        DataFrame with columns:
        - spread: Point spread
        - spread_percent: Percentage spread
        - zscore: Statistical z-score
    """
    df = pd.DataFrame(index=ma_short.index)
    df['spread'] = calculate_ma_spread(ma_short, ma_long)
    df['spread_percent'] = calculate_ma_spread_percent(ma_short, ma_long)
    df['zscore'] = calculate_ma_spread_zscore(ma_short, ma_long, lookback)
    
    return df


# ==============================================================================
# STATISTICAL HELPERS
# ==============================================================================

def calculate_rolling_stats(series: pd.Series, window: int) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate rolling mean and standard deviation.
    
    Args:
        series: Input data series
        window: Rolling window size
    
    Returns:
        Tuple of (rolling_mean, rolling_std)
    """
    rolling_mean = series.rolling(window=window, min_periods=window).mean()
    rolling_std = series.rolling(window=window, min_periods=window).std()
    return rolling_mean, rolling_std


def determine_signal(zscore: float, threshold: float = 2.0) -> str:
    """
    Determine mean reversion signal from z-score.
    
    Args:
        zscore: Statistical z-score
        threshold: Extreme threshold (default: 2.0)
    
    Returns:
        Signal description string
    """
    if pd.isna(zscore):
        return "insufficient_data"
    elif zscore > threshold:
        return "extremely_overbought"
    elif zscore > 1:
        return "moderately_overbought"
    elif zscore < -threshold:
        return "extremely_oversold"
    elif zscore < -1:
        return "moderately_oversold"
    else:
        return "normal_range"


def determine_trend_alignment(ma_20: float, ma_50: float, ma_200: float) -> str:
    """
    Determine if MAs are in bullish or bearish alignment.
    
    Args:
        ma_20: 20-day MA value
        ma_50: 50-day MA value
        ma_200: 200-day MA value
    
    Returns:
        Alignment description
    """
    if pd.isna(ma_20) or pd.isna(ma_50) or pd.isna(ma_200):
        return "insufficient_data"
    
    if ma_20 > ma_50 > ma_200:
        return "strong_bullish"
    elif ma_20 > ma_50:
        return "moderate_bullish"
    elif ma_20 < ma_50 < ma_200:
        return "strong_bearish"
    elif ma_20 < ma_50:
        return "moderate_bearish"
    else:
        return "mixed"


# ==============================================================================
# DATA FORMATTING AND SERIALIZATION
# ==============================================================================

def safe_float(value, decimals: int = 2) -> Optional[float]:
    """
    Safely convert value to float with rounding, handling NaN/inf.
    
    Args:
        value: Value to convert
        decimals: Number of decimal places
    
    Returns:
        Rounded float or None for invalid values
    """
    if pd.isna(value) or np.isinf(value):
        return None
    return round(float(value), decimals)


def format_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def format_date(dt: datetime) -> str:
    """Format datetime as YYYY-MM-DD."""
    return dt.strftime('%Y-%m-%d')


def create_snapshot_record(
    date: str,
    symbol: str,
    price: float,
    ma_values: Dict[str, float],
    metrics: Dict[str, float]
) -> Dict:
    """
    Create a formatted snapshot record for current values.
    
    Args:
        date: Date string (YYYY-MM-DD)
        symbol: ETF symbol
        price: Current price
        ma_values: Dict of MA values
        metrics: Dict of calculated metrics
    
    Returns:
        Formatted dictionary
    """
    record = {
        'date': date,
        'symbol': symbol,
        'price': safe_float(price),
        'moving_averages': ma_values,
        'metrics': metrics
    }
    return record


def create_historical_record(
    date: str,
    price: float,
    ma_values: Dict[str, Optional[float]],
    metrics: Dict[str, Optional[float]]
) -> Dict:
    """
    Create a formatted historical record for time series data.
    
    Args:
        date: Date string
        price: Price value
        ma_values: Dict of MA values
        metrics: Dict of metrics
    
    Returns:
        Formatted dictionary
    """
    return {
        'date': date,
        'price': safe_float(price),
        'moving_averages': {k: safe_float(v) for k, v in ma_values.items()},
        'metrics': {k: safe_float(v) for k, v in metrics.items()}
    }


def save_json(data: Dict, filepath: str, indent: int = 2):
    """
    Save data to JSON file with proper formatting.
    
    Args:
        data: Dictionary to save
        filepath: Output file path
        indent: JSON indentation (default: 2)
    """
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def create_metadata(
    indices_count: int,
    data_source: str = "Yahoo Finance (yfinance)",
    description: str = ""
) -> Dict:
    """
    Create metadata section for JSON output.
    
    Args:
        indices_count: Number of indices tracked
        data_source: Data source description
        description: Additional description
    
    Returns:
        Metadata dictionary
    """
    return {
        'generated_at': format_timestamp(),
        'data_source': data_source,
        'etfs_count': etfs_count,
        'description': description,
        'calculation_note': 'All metrics use adjusted closing prices'
    }


# ==============================================================================
# DATA VALIDATION
# ==============================================================================

def validate_sufficient_data(df: pd.DataFrame, min_periods: int) -> bool:
    """
    Check if DataFrame has sufficient non-null data.
    
    Args:
        df: DataFrame to check
        min_periods: Minimum required periods
    
    Returns:
        True if sufficient data exists
    """
    if len(df) < min_periods:
        return False
    # Check if we have enough non-null values
    non_null_count = df.notna().sum().min() if len(df.columns) > 0 else len(df)
    return non_null_count >= min_periods


def get_data_quality_status(df: pd.DataFrame, required_periods: int) -> Dict:
    """
    Assess data quality and completeness.
    
    Args:
        df: DataFrame to assess
        required_periods: Required number of periods
    
    Returns:
        Dict with quality metrics
    """
    actual_periods = len(df)
    completeness = (actual_periods / required_periods) * 100 if required_periods > 0 else 0
    
    return {
        'required_periods': required_periods,
        'actual_periods': actual_periods,
        'completeness_percent': round(completeness, 1),
        'sufficient_data': actual_periods >= required_periods
    }
