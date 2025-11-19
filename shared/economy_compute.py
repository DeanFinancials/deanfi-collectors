#!/usr/bin/env python3
"""
Computation and Analysis
Handles data calculations, grading, and trend analysis.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from datetime import datetime


def calculate_percentile_rank(series: pd.Series, current_value: float) -> float:
    """
    Calculate percentile rank of current value within historical series.
    
    Args:
        series: Historical data series
        current_value: Current value to rank
        
    Returns:
        Percentile rank (0-100)
    """
    if series.empty or pd.isna(current_value):
        return 50.0  # Default to neutral
    
    # Remove NaN values
    valid_series = series.dropna()
    if len(valid_series) == 0:
        return 50.0
    
    # Calculate percentile
    below_count = (valid_series < current_value).sum()
    percentile = (below_count / len(valid_series)) * 100.0
    
    return round(percentile, 2)


def calculate_grade(
    percentile: float,
    interpretation: str = "higher_is_better"
) -> Dict[str, Any]:
    """
    Calculate grade based on percentile and interpretation.
    
    For "higher_is_better" indicators:
    - A+: 90-100th percentile (Excellent)
    - A:  75-90th percentile (Very Good)
    - B:  50-75th percentile (Good)
    - C:  25-50th percentile (Fair)
    - D:  0-25th percentile (Poor)
    
    For "lower_is_better" indicators (inverted):
    - A+: 0-10th percentile (Excellent)
    - A:  10-25th percentile (Very Good)
    - B:  25-50th percentile (Good)
    - C:  50-75th percentile (Fair)
    - D:  75-100th percentile (Poor)
    
    For "neutral" indicators:
    - Use middle 50% (25-75th) as optimal range
    
    Args:
        percentile: Percentile rank (0-100)
        interpretation: One of "higher_is_better", "lower_is_better", "neutral"
        
    Returns:
        Dictionary with grade, label, color, and points
    """
    if interpretation == "higher_is_better":
        if percentile >= 90:
            return {
                "grade": "A+",
                "label": "Excellent",
                "color": "success",
                "points": 5
            }
        elif percentile >= 75:
            return {
                "grade": "A",
                "label": "Very Good",
                "color": "success",
                "points": 4
            }
        elif percentile >= 50:
            return {
                "grade": "B",
                "label": "Good",
                "color": "warning",
                "points": 3
            }
        elif percentile >= 25:
            return {
                "grade": "C",
                "label": "Fair",
                "color": "warning",
                "points": 2
            }
        else:
            return {
                "grade": "D",
                "label": "Poor",
                "color": "destructive",
                "points": 1
            }
    
    elif interpretation == "lower_is_better":
        # Invert the percentile for grading
        if percentile <= 10:
            return {
                "grade": "A+",
                "label": "Excellent",
                "color": "success",
                "points": 5
            }
        elif percentile <= 25:
            return {
                "grade": "A",
                "label": "Very Good",
                "color": "success",
                "points": 4
            }
        elif percentile <= 50:
            return {
                "grade": "B",
                "label": "Good",
                "color": "warning",
                "points": 3
            }
        elif percentile <= 75:
            return {
                "grade": "C",
                "label": "Fair",
                "color": "warning",
                "points": 2
            }
        else:
            return {
                "grade": "D",
                "label": "Poor",
                "color": "destructive",
                "points": 1
            }
    
    else:  # neutral
        # For neutral indicators, middle range is best
        distance_from_50 = abs(percentile - 50)
        
        if distance_from_50 <= 10:  # 40-60th percentile
            return {
                "grade": "A+",
                "label": "Optimal Range",
                "color": "success",
                "points": 5
            }
        elif distance_from_50 <= 25:  # 25-75th percentile
            return {
                "grade": "A",
                "label": "Normal Range",
                "color": "success",
                "points": 4
            }
        elif distance_from_50 <= 35:  # 15-85th percentile
            return {
                "grade": "B",
                "label": "Acceptable",
                "color": "warning",
                "points": 3
            }
        elif distance_from_50 <= 45:  # 5-95th percentile
            return {
                "grade": "C",
                "label": "Concerning",
                "color": "destructive",
                "points": 2
            }
        else:  # Extremes (0-5th or 95-100th)
            return {
                "grade": "D",
                "label": "Extreme",
                "color": "destructive",
                "points": 1
            }


def calculate_overall_grade(grades: list) -> Dict[str, Any]:
    """
    Calculate overall grade from individual indicator grades.
    
    Args:
        grades: List of grade dictionaries
        
    Returns:
        Overall grade dictionary
    """
    if not grades:
        return {
            "grade": "N/A",
            "label": "Insufficient Data",
            "color": "muted",
            "points": 0
        }
    
    # Calculate average points
    total_points = sum(g.get("points", 0) for g in grades)
    avg_points = total_points / len(grades)
    
    # Convert average points to grade
    if avg_points >= 4.5:
        return {
            "grade": "A+",
            "label": "Excellent",
            "color": "success",
            "points": round(avg_points, 1)
        }
    elif avg_points >= 3.5:
        return {
            "grade": "A",
            "label": "Very Good",
            "color": "success",
            "points": round(avg_points, 1)
        }
    elif avg_points >= 2.5:
        return {
            "grade": "B",
            "label": "Good",
            "color": "warning",
            "points": round(avg_points, 1)
        }
    elif avg_points >= 1.5:
        return {
            "grade": "C",
            "label": "Fair",
            "color": "warning",
            "points": round(avg_points, 1)
        }
    else:
        return {
            "grade": "D",
            "label": "Poor",
            "color": "destructive",
            "points": round(avg_points, 1)
        }


def calculate_trend(
    current: float,
    previous: float,
    threshold: float = 0.01
) -> str:
    """
    Determine trend direction.
    
    Args:
        current: Current value
        previous: Previous value
        threshold: Minimum percent change to count as trend (default 1%)
        
    Returns:
        "improving", "declining", or "stable"
    """
    if pd.isna(current) or pd.isna(previous) or previous == 0:
        return "stable"
    
    pct_change = ((current - previous) / abs(previous)) * 100
    
    if abs(pct_change) < threshold:
        return "stable"
    elif pct_change > 0:
        return "improving"
    else:
        return "declining"


def calculate_change_metrics(
    df: pd.DataFrame,
    periods: Optional[Dict[str, int]] = None,
    frequency: str = "Monthly"
) -> Dict[str, Optional[float]]:
    """
    Calculate various change metrics for a time series.
    
    V2: Updated to support year-based periods aligned with chart tabs.
    
    Args:
        df: DataFrame with 'date' and 'value' columns
        periods: Dictionary mapping metric name to number of periods
                 If None, uses year-based defaults: {"1y": 12, "5y": 60, "10y": 120, "20y": 240}
                 for monthly data, adjusted for other frequencies
        frequency: Data frequency ("Quarterly", "Monthly", "Weekly", "Daily")
                 
    Returns:
        Dictionary of change metrics
    """
    if df.empty or "value" not in df.columns:
        return {}
    
    df_clean = df.dropna(subset=["value"])
    
    if df_clean.empty:
        return {"1y": None, "5y": None, "10y": None, "20y": None}
    
    # V2: Default to year-based periods if not specified
    if periods is None:
        freq_lower = frequency.lower()
        if freq_lower == "quarterly":
            # Quarterly: 4 periods per year
            periods = {"1y": 4, "5y": 20, "10y": 40, "20y": 80}
        elif freq_lower == "monthly":
            # Monthly: 12 periods per year
            periods = {"1y": 12, "5y": 60, "10y": 120, "20y": 240}
        elif freq_lower == "weekly":
            # Weekly: ~52 periods per year
            periods = {"1y": 52, "5y": 260, "10y": 520, "20y": 1040}
        elif freq_lower == "daily":
            # Daily: ~252 trading days per year
            periods = {"1y": 252, "5y": 1260, "10y": 2520, "20y": 5040}
        else:
            # Default to monthly
            periods = {"1y": 12, "5y": 60, "10y": 120, "20y": 240}
    
    changes = {}
    current_value = df_clean.iloc[-1]["value"]
    
    for period_name, num_periods in periods.items():
        if len(df_clean) > num_periods:
            past_value = df_clean.iloc[-(num_periods + 1)]["value"]
            if past_value != 0:
                pct_change = ((current_value - past_value) / abs(past_value)) * 100
                changes[period_name] = round(pct_change, 2)
            else:
                changes[period_name] = None
        else:
            changes[period_name] = None
    
    return changes


def calculate_derived_gdp_growth(gdp_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate quarter-over-quarter GDP growth rate from GDPC1 series.
    
    Args:
        gdp_df: DataFrame with GDPC1 data (date, value)
        
    Returns:
        DataFrame with GDP growth rates
    """
    if gdp_df.empty:
        return pd.DataFrame(columns=["date", "value"])
    
    df = gdp_df.copy()
    df = df.sort_values("date").reset_index(drop=True)
    
    # Calculate percent change from previous quarter
    df["value"] = df["value"].pct_change() * 100
    
    # Remove first row (will be NaN)
    df = df.dropna(subset=["value"]).reset_index(drop=True)
    
    return df


def calculate_derived_yield_spread(
    dgs10_df: pd.DataFrame,
    dgs2_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Calculate 10Y-2Y Treasury yield spread.
    
    Args:
        dgs10_df: DataFrame with 10-year yield data
        dgs2_df: DataFrame with 2-year yield data
        
    Returns:
        DataFrame with yield spread
    """
    if dgs10_df.empty or dgs2_df.empty:
        return pd.DataFrame(columns=["date", "value"])
    
    # Merge on date
    merged = pd.merge(
        dgs10_df.rename(columns={"value": "dgs10"}),
        dgs2_df.rename(columns={"value": "dgs2"}),
        on="date",
        how="inner"
    )
    
    # Calculate spread
    merged["value"] = merged["dgs10"] - merged["dgs2"]
    
    return merged[["date", "value"]]


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize data structure for JSON serialization.
    Converts NaN, inf, and -inf to None.
    
    Args:
        obj: Object to sanitize
        
    Returns:
        JSON-safe object
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    elif isinstance(obj, (np.ndarray, pd.Series)):
        return sanitize_for_json(obj.tolist())
    elif isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    elif isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%d")
    else:
        return obj


def adaptive_resample(
    df: pd.DataFrame,
    native_frequency: str,
    series_id: Optional[str] = None
) -> pd.DataFrame:
    """
    Intelligently downsample time series based on native frequency.
    
    V2 Strategy:
    - Quarterly data: Keep as-is (natural economic reporting cycle)
    - Monthly data: Keep as-is (optimal balance of detail vs volume)
    - Weekly data: Downsample to monthly using mean (e.g., weekly claims → monthly avg)
    - Daily data: Downsample to monthly using last value (end-of-period snapshots)
    
    Args:
        df: DataFrame with 'date' and 'value' columns
        native_frequency: Original frequency ("Quarterly", "Monthly", "Weekly", "Daily")
        series_id: Optional series identifier for special handling (e.g., ICSA)
        
    Returns:
        Resampled DataFrame with 'date' and 'value' columns
    """
    if df.empty or "value" not in df.columns:
        return df
    
    freq_lower = native_frequency.lower()
    
    # Keep quarterly and monthly data as-is
    if freq_lower in ["quarterly", "monthly"]:
        return df
    
    # For weekly and daily data, downsample to monthly
    df_copy = df.copy()
    df_copy = df_copy.sort_values("date").reset_index(drop=True)
    df_copy.set_index("date", inplace=True)
    
    if freq_lower == "weekly":
        # Weekly → Monthly: Use mean (better for flow data like jobless claims)
        monthly = df_copy.resample('ME').mean()
    elif freq_lower == "daily":
        # Daily → Monthly: Use last value (end-of-period snapshot)
        # Exception: For specific series that benefit from averaging
        if series_id == "ICSA":  # Weekly claims reported daily
            monthly = df_copy.resample('ME').mean()
        else:
            monthly = df_copy.resample('ME').last()
    else:
        # Unknown frequency: default to monthly last
        monthly = df_copy.resample('ME').last()
    
    # Reset index and clean up
    monthly = monthly.reset_index()
    monthly = monthly.dropna(subset=["value"])
    
    return monthly
