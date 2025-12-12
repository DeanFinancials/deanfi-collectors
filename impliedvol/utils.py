"""
Utility functions for implied volatility analysis.

Provides:
- IV moving averages (20-day, 50-day)
- ATM option selection
- Option liquidity metrics
- Moneyness calculation
- JSON serialization helpers
- Historical IV reference ranges
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# Use Eastern Time for market data timestamps
ET = ZoneInfo('America/New_York')


# Historical IV Reference Ranges (based on market research)
# Source: Barchart, AlphaQuery, Investopedia (Nov 2025)
IV_HISTORICAL_AVERAGES = {
    # Major Indices
    "SPY": {
        "historical_avg": 0.17,
        "historical_avg_formatted": "17%",
        "typical_range": {"low": 0.12, "high": 0.25},
        "description": "S&P 500 ETF - Broad market benchmark"
    },
    "QQQ": {
        "historical_avg": 0.22,
        "historical_avg_formatted": "22%",
        "typical_range": {"low": 0.15, "high": 0.30},
        "description": "Nasdaq-100 ETF - Tech-heavy index"
    },
    "IWM": {
        "historical_avg": 0.24,
        "historical_avg_formatted": "24%",
        "typical_range": {"low": 0.18, "high": 0.32},
        "description": "Russell 2000 ETF - Small cap stocks"
    },
    "DIA": {
        "historical_avg": 0.16,
        "historical_avg_formatted": "16%",
        "typical_range": {"low": 0.11, "high": 0.23},
        "description": "Dow Jones Industrial Average ETF"
    },
    
    # Sector ETFs
    "XLK": {
        "historical_avg": 0.23,
        "historical_avg_formatted": "23%",
        "typical_range": {"low": 0.16, "high": 0.32},
        "description": "Technology Select Sector"
    },
    "XLV": {
        "historical_avg": 0.18,
        "historical_avg_formatted": "18%",
        "typical_range": {"low": 0.13, "high": 0.25},
        "description": "Health Care Select Sector"
    },
    "XLF": {
        "historical_avg": 0.21,
        "historical_avg_formatted": "21%",
        "typical_range": {"low": 0.15, "high": 0.30},
        "description": "Financial Select Sector"
    },
    "XLE": {
        "historical_avg": 0.28,
        "historical_avg_formatted": "28%",
        "typical_range": {"low": 0.20, "high": 0.40},
        "description": "Energy Select Sector"
    },
    "XLY": {
        "historical_avg": 0.20,
        "historical_avg_formatted": "20%",
        "typical_range": {"low": 0.14, "high": 0.28},
        "description": "Consumer Discretionary Select Sector"
    },
    "XLP": {
        "historical_avg": 0.15,
        "historical_avg_formatted": "15%",
        "typical_range": {"low": 0.11, "high": 0.21},
        "description": "Consumer Staples Select Sector"
    },
    "XLI": {
        "historical_avg": 0.19,
        "historical_avg_formatted": "19%",
        "typical_range": {"low": 0.14, "high": 0.26},
        "description": "Industrial Select Sector"
    },
    "XLU": {
        "historical_avg": 0.17,
        "historical_avg_formatted": "17%",
        "typical_range": {"low": 0.12, "high": 0.24},
        "description": "Utilities Select Sector"
    },
    "XLB": {
        "historical_avg": 0.22,
        "historical_avg_formatted": "22%",
        "typical_range": {"low": 0.16, "high": 0.30},
        "description": "Materials Select Sector"
    },
    "XLRE": {
        "historical_avg": 0.20,
        "historical_avg_formatted": "20%",
        "typical_range": {"low": 0.14, "high": 0.28},
        "description": "Real Estate Select Sector"
    },
    "XLC": {
        "historical_avg": 0.24,
        "historical_avg_formatted": "24%",
        "typical_range": {"low": 0.17, "high": 0.33},
        "description": "Communication Services Select Sector"
    },
    
    # VIX (Volatility Index)
    "^VIX": {
        "historical_avg": 0.21,
        "historical_avg_formatted": "21%",
        "typical_range": {"low": 0.12, "high": 0.30},
        "description": "CBOE Volatility Index - Market fear gauge",
        "special_note": "VIX > 30 indicates high market uncertainty"
    }
}


def get_iv_historical_reference(symbol: str) -> Dict:
    """
    Get historical IV reference data for a symbol.
    
    Args:
        symbol: Ticker symbol
        
    Returns:
        Dictionary with historical average and typical range
    """
    return IV_HISTORICAL_AVERAGES.get(symbol, {
        "historical_avg": None,
        "historical_avg_formatted": "N/A",
        "typical_range": {"low": None, "high": None},
        "description": "Unknown symbol"
    })


def calculate_iv_ma(iv_series: pd.Series, periods: List[int] = [20, 50]) -> Dict[str, float]:
    """
    Calculate implied volatility moving averages.
    
    Args:
        iv_series: Series of IV values (index = date, values = IV)
        periods: List of MA periods to calculate
    
    Returns:
        Dict with 'iv_ma_20', 'iv_ma_50', etc.
    """
    result = {}
    
    for period in periods:
        if len(iv_series) >= period:
            ma_value = iv_series.tail(period).mean()
            result[f'iv_ma_{period}'] = round(ma_value, 6)
        else:
            result[f'iv_ma_{period}'] = None
    
    return result


def find_atm_option(options_df: pd.DataFrame, 
                    underlying_price: float,
                    tolerance: float = 0.02) -> Optional[pd.Series]:
    """
    Find the at-the-money (ATM) option from options DataFrame.
    
    Args:
        options_df: DataFrame with option chain data
        underlying_price: Current price of underlying
        tolerance: Max % difference from ATM (default 2%)
    
    Returns:
        Series with ATM option data, or None if not found
    """
    if len(options_df) == 0:
        return None
    
    # Calculate distance from ATM
    options_df = options_df.copy()
    options_df['strike_diff'] = abs(options_df['strike'] - underlying_price)
    options_df['strike_pct_diff'] = options_df['strike_diff'] / underlying_price
    
    # Filter within tolerance
    atm_options = options_df[options_df['strike_pct_diff'] <= tolerance]
    
    if len(atm_options) == 0:
        # If none within tolerance, take closest
        atm_idx = options_df['strike_diff'].idxmin()
        return options_df.loc[atm_idx]
    
    # Find closest to ATM
    atm_idx = atm_options['strike_diff'].idxmin()
    return atm_options.loc[atm_idx]


def calculate_moneyness(strike: float, underlying_price: float) -> Dict[str, any]:
    """
    Calculate option moneyness metrics.
    
    Args:
        strike: Option strike price
        underlying_price: Current underlying price
    
    Returns:
        Dict with moneyness, pct_from_atm, classification
    """
    moneyness = strike / underlying_price
    pct_from_atm = ((strike - underlying_price) / underlying_price) * 100
    
    # Classification
    if abs(pct_from_atm) <= 2:
        classification = "ATM"
    elif pct_from_atm > 2:
        classification = "OTM" if strike > underlying_price else "ITM"
    else:
        classification = "ITM" if strike < underlying_price else "OTM"
    
    return {
        'moneyness': round(moneyness, 4),
        'pct_from_atm': round(pct_from_atm, 2),
        'classification': classification
    }


def calculate_option_liquidity(option: pd.Series) -> Dict[str, any]:
    """
    Calculate option liquidity metrics.
    
    Args:
        option: Series with option data (volume, openInterest, bid, ask)
    
    Returns:
        Dict with liquidity metrics
    """
    volume = option.get('volume', 0)
    open_interest = option.get('openInterest', 0)
    bid = option.get('bid', 0)
    ask = option.get('ask', 0)
    
    # Bid-ask spread
    spread = ask - bid if (bid > 0 and ask > 0) else None
    spread_pct = (spread / ((bid + ask) / 2) * 100) if spread and (bid + ask) > 0 else None
    
    return {
        'volume': int(volume) if pd.notna(volume) else 0,
        'open_interest': int(open_interest) if pd.notna(open_interest) else 0,
        'bid_ask_spread': round(spread, 4) if spread else None,
        'spread_pct': round(spread_pct, 2) if spread_pct else None
    }


def filter_options_by_dte(ticker: yf.Ticker, 
                          min_dte: int = 7,
                          max_dte: int = 60) -> Optional[Tuple[str, pd.DataFrame, pd.DataFrame]]:
    """
    Get option chain filtered by days to expiration.
    
    Args:
        ticker: yfinance Ticker object
        min_dte: Minimum days to expiration
        max_dte: Maximum days to expiration
    
    Returns:
        Tuple of (expiration_date, calls_df, puts_df) or None
    """
    try:
        expirations = ticker.options
        if not expirations:
            return None
        
        today = datetime.now().date()
        
        # Find expiration within DTE range
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            dte = (exp_date - today).days
            
            if min_dte <= dte <= max_dte:
                # Get option chain
                opt_chain = ticker.option_chain(exp_str)
                return (exp_str, opt_chain.calls, opt_chain.puts)
        
        # If no expiration in range, use nearest
        nearest_exp = expirations[0]
        opt_chain = ticker.option_chain(nearest_exp)
        return (nearest_exp, opt_chain.calls, opt_chain.puts)
        
    except Exception as e:
        print(f"Error filtering options: {e}")
        return None


def get_option_snapshot(symbol: str,
                       min_dte: int = 7,
                       max_dte: int = 60,
                       atm_tolerance: float = 0.02) -> Optional[Dict]:
    """
    Get comprehensive option snapshot for a symbol.
    
    Args:
        symbol: Ticker symbol
        min_dte: Minimum days to expiration
        max_dte: Maximum days to expiration
        atm_tolerance: ATM tolerance (%)
    
    Returns:
        Dict with current price, ATM call/put IV, option details
    """
    try:
        ticker = yf.Ticker(symbol)
        
        # Get current price
        hist = ticker.history(period="1d")
        if len(hist) == 0:
            return None
        
        current_price = hist['Close'].iloc[-1]
        
        # Get options
        opt_data = filter_options_by_dte(ticker, min_dte, max_dte)
        if not opt_data:
            return None
        
        exp_date, calls, puts = opt_data
        
        # Calculate DTE
        exp_dt = datetime.strptime(exp_date, '%Y-%m-%d').date()
        today = datetime.now().date()
        dte = (exp_dt - today).days
        
        # Find ATM options
        atm_call = find_atm_option(calls, current_price, atm_tolerance)
        atm_put = find_atm_option(puts, current_price, atm_tolerance)
        
        if atm_call is None or atm_put is None:
            return None
        
        # Build snapshot
        snapshot = {
            'symbol': symbol,
            'current_price': round(current_price, 2),
            'timestamp': datetime.now(ET).isoformat(),
            'expiration_date': exp_date,
            'days_to_expiration': dte,
            
            # ATM Call data
            'atm_call': {
                'strike': float(atm_call['strike']),
                'implied_volatility': round(float(atm_call['impliedVolatility']), 6),
                'last_price': round(float(atm_call['lastPrice']), 4),
                'bid': round(float(atm_call['bid']), 4),
                'ask': round(float(atm_call['ask']), 4),
                'mid_price': round((float(atm_call['bid']) + float(atm_call['ask'])) / 2, 4),
                **calculate_moneyness(float(atm_call['strike']), current_price),
                **calculate_option_liquidity(atm_call)
            },
            
            # ATM Put data
            'atm_put': {
                'strike': float(atm_put['strike']),
                'implied_volatility': round(float(atm_put['impliedVolatility']), 6),
                'last_price': round(float(atm_put['lastPrice']), 4),
                'bid': round(float(atm_put['bid']), 4),
                'ask': round(float(atm_put['ask']), 4),
                'mid_price': round((float(atm_put['bid']) + float(atm_put['ask'])) / 2, 4),
                **calculate_moneyness(float(atm_put['strike']), current_price),
                **calculate_option_liquidity(atm_put)
            },
            
            # Average IV (mid of ATM call and put)
            'average_iv': round((float(atm_call['impliedVolatility']) + float(atm_put['impliedVolatility'])) / 2, 6)
        }
        
        return snapshot
        
    except Exception as e:
        print(f"Error getting option snapshot for {symbol}: {e}")
        return None


def get_historical_iv(symbol: str,
                     lookback_days: int = 252,
                     min_dte: int = 7,
                     max_dte: int = 60) -> Optional[pd.DataFrame]:
    """
    Get historical ATM implied volatility data.
    
    Note: This function fetches historical price data and attempts to 
    reconstruct what ATM IV would have been. Since yfinance doesn't provide
    historical option chains, we can only get current snapshots.
    
    For true historical IV, we'd need to:
    1. Store daily snapshots ourselves
    2. Use a paid data provider (CBOE, IVolatility, etc.)
    
    This function will return a DataFrame with dates and placeholder for IV
    that should be populated from daily fetcher runs.
    
    Args:
        symbol: Ticker symbol
        lookback_days: Number of days to look back
        min_dte: Minimum DTE for options
        max_dte: Maximum DTE for options
    
    Returns:
        DataFrame with date index and 'average_iv' column
    """
    try:
        ticker = yf.Ticker(symbol)
        
        # Get historical prices to establish date range
        hist = ticker.history(period=f"{lookback_days}d")
        
        if len(hist) == 0:
            return None
        
        # Create DataFrame with dates
        df = pd.DataFrame(index=hist.index)
        df['date'] = df.index.strftime('%Y-%m-%d')
        df['close'] = hist['Close']
        
        # Placeholder for IV - to be populated from daily snapshots
        df['average_iv'] = None
        
        # Get current IV snapshot and add as most recent
        current_snapshot = get_option_snapshot(symbol, min_dte, max_dte)
        if current_snapshot:
            # Add today's IV
            today = datetime.now().date()
            if today.strftime('%Y-%m-%d') in df['date'].values:
                df.loc[df['date'] == today.strftime('%Y-%m-%d'), 'average_iv'] = current_snapshot['average_iv']
        
        return df[['date', 'close', 'average_iv']].reset_index(drop=True)
        
    except Exception as e:
        print(f"Error getting historical IV for {symbol}: {e}")
        return None


def serialize_for_json(obj):
    """
    Convert numpy/pandas types to JSON-serializable Python types.
    
    Args:
        obj: Object to serialize
    
    Returns:
        JSON-serializable object
    """
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif pd.isna(obj):
        return None
    else:
        return obj


def format_iv_percentage(iv: float) -> str:
    """
    Format IV as percentage string.
    
    Args:
        iv: Implied volatility (0.25 = 25%)
    
    Returns:
        Formatted string like "25.00%"
    """
    return f"{iv * 100:.2f}%"


def classify_iv_level(iv: float, iv_ma_20: Optional[float] = None) -> str:
    """
    Classify IV level (Low, Normal, Elevated, High, Extreme).
    
    Args:
        iv: Current implied volatility
        iv_ma_20: 20-day IV moving average (optional)
    
    Returns:
        Classification string
    """
    # Absolute levels
    if iv < 0.15:
        abs_level = "Low"
    elif iv < 0.25:
        abs_level = "Normal"
    elif iv < 0.35:
        abs_level = "Elevated"
    elif iv < 0.50:
        abs_level = "High"
    else:
        abs_level = "Extreme"
    
    # Relative to MA (if available)
    if iv_ma_20:
        pct_above_ma = ((iv - iv_ma_20) / iv_ma_20) * 100
        if pct_above_ma > 20:
            rel_level = " (Above Normal)"
        elif pct_above_ma < -20:
            rel_level = " (Below Normal)"
        else:
            rel_level = ""
        
        return abs_level + rel_level
    
    return abs_level


def calculate_iv_percentile(current_iv: float, historical_iv: pd.Series) -> Optional[float]:
    """
    Calculate IV percentile rank (where current IV stands in historical range).
    
    Args:
        current_iv: Current implied volatility
        historical_iv: Series of historical IV values
    
    Returns:
        Percentile (0-100) or None if insufficient data
    """
    if len(historical_iv.dropna()) < 20:
        return None
    
    percentile = (historical_iv.dropna() < current_iv).sum() / len(historical_iv.dropna()) * 100
    return round(percentile, 1)


def get_iv_summary_stats(iv_series: pd.Series) -> Dict[str, float]:
    """
    Calculate summary statistics for IV series.
    
    Args:
        iv_series: Series of IV values
    
    Returns:
        Dict with min, max, mean, median, std
    """
    if len(iv_series.dropna()) == 0:
        return {
            'min': None,
            'max': None,
            'mean': None,
            'median': None,
            'std': None
        }
    
    return {
        'min': round(iv_series.min(), 6),
        'max': round(iv_series.max(), 6),
        'mean': round(iv_series.mean(), 6),
        'median': round(iv_series.median(), 6),
        'std': round(iv_series.std(), 6)
    }
