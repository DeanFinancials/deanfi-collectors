#!/usr/bin/env python3
"""
Export Growth & Output economic indicators to JSON.
Includes: GDP, GDP Growth Rate, Industrial Production, Capacity Utilization, Leading Economic Index
"""
import argparse
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add shared to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SHARED_DIR = REPO_ROOT / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from fred_client import FREDClient
from economy_indicators import get_indicators_by_category
from economy_compute import (
    calculate_percentile_rank,
    calculate_grade,
    calculate_overall_grade,
    calculate_trend,
    is_trend_favorable,
    calculate_change_metrics,
    calculate_derived_gdp_growth,
    adaptive_resample,
    sanitize_for_json
)
from economy_io import load_config, save_json


def export_growth_output_json(
    output_path: str,
    config_path: str = None,
    override_history_days: int = None
) -> dict:
    """
    Generate Growth & Output indicators JSON.
    
    Args:
        output_path: Path to write JSON file
        config_path: Path to config YAML (uses defaults if None)
        override_history_days: If specified, overrides frequency-based calculation
        
    Returns:
        Dictionary containing indicator data
    """
    # Load configuration
    config = load_config(config_path)
    
    # Initialize FRED client
    fred = FREDClient(rate_limit=config.get("fred", {}).get("rate_limit_seconds", 0.1))
    
    # Get indicator definitions
    indicators = get_indicators_by_category("growth_output")
    
    # V2: Calculate 20 years of history for robust percentile calculations
    if override_history_days:
        history_days = override_history_days
    else:
        # Always fetch 20 years (7300 days) for meaningful historical context
        history_days = 7300
    
    # Calculate date range - fetch full 20 years
    end_date = datetime.now()
    start_date = end_date - timedelta(days=history_days)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Fetching Growth & Output data from {start_date_str} to {end_date_str}...")
    print(f"  (20-year lookback for robust percentile calculations)")
    
    # Fetch data for all indicators
    indicator_data = {}
    
    for indicator in indicators:
        if indicator.is_derived:
            continue  # Handle derived indicators separately
        
        print(f"  Fetching {indicator.series_id} ({indicator.name})...")
        df = fred.get_series_range(indicator.series_id, start_date_str, end_date_str)
        indicator_data[indicator.series_id] = df
    
    # Calculate derived indicators (before resampling for accuracy)
    if "GDPC1" in indicator_data and not indicator_data["GDPC1"].empty:
        print("  Calculating GDP Growth Rate...")
        gdp_growth = calculate_derived_gdp_growth(indicator_data["GDPC1"])
        indicator_data["GDP_GROWTH"] = gdp_growth
    
    # Build JSON structure
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)
    
    json_data = {
        "metadata": {
            "generated_at": now.isoformat(),
            "data_source": "FRED API",
            "category": "Growth & Output",
            "indicators": [
                {
                    "series_id": ind.series_id,
                    "name": ind.name,
                    "frequency": ind.frequency,
                    "unit": ind.unit
                }
                for ind in indicators
            ],
            "history_days": history_days,
            "data_start": start_date_str,
            "data_end": end_date_str
        },
        "current": {
            "date": None,
            "overall_grade": {},
            "indicators": {}
        },
        "history": {
            "series": {}  # Each series will have its own dates and values
        }
    }
    
    # Process each indicator for current values and grades
    grades = []
    
    for indicator in indicators:
        series_id = indicator.series_id
        
        if series_id not in indicator_data or indicator_data[series_id].empty:
            print(f"  Warning: No data for {series_id}")
            continue
        
        df = indicator_data[series_id]
        df_clean = df.dropna(subset=["value"])
        
        if df_clean.empty:
            continue
        
        # Get current value and date
        current_value = df_clean.iloc[-1]["value"]
        current_date = df_clean.iloc[-1]["date"]
        
        # Get previous value for trend
        previous_value = df_clean.iloc[-2]["value"] if len(df_clean) > 1 else current_value
        
        # V2: Calculate percentile rank on FULL 20-year dataset
        historical_values = df_clean["value"]
        percentile = calculate_percentile_rank(historical_values, current_value)
        
        # Calculate grade
        grade = calculate_grade(percentile, indicator.interpretation)
        grades.append(grade)
        
        # Calculate trend
        trend = calculate_trend(current_value, previous_value)
        is_favorable = is_trend_favorable(trend, indicator.interpretation)
        
        # V2: Calculate year-based change metrics aligned with chart tabs
        changes = calculate_change_metrics(df_clean, frequency=indicator.frequency)
        
        # Update current date (use most recent)
        if json_data["current"]["date"] is None:
            json_data["current"]["date"] = current_date.strftime("%Y-%m-%d")
        
        # Add to current indicators
        json_data["current"]["indicators"][series_id] = {
            "name": indicator.name,
            "value": round(current_value, 2) if current_value else None,
            "unit": indicator.unit,
            "frequency": indicator.frequency,
            "percentile": percentile,
            "grade": grade,
            "trend": trend,
            "is_favorable": is_favorable,
            "changes": changes,
            "interpretation": indicator.interpretation
        }
        
        # V2: Apply adaptive resampling for storage
        # Quarterly/Monthly data kept as-is, Weekly/Daily downsampled to monthly
        print(f"  Resampling {series_id} ({indicator.frequency} → storage format)...")
        df_resampled = adaptive_resample(df_clean, indicator.frequency, series_id)
        
        # Store resampled history (full 20 years after resampling)
        if not df_resampled.empty:
            json_data["history"]["series"][series_id] = {
                "dates": [d.strftime("%Y-%m-%d") for d in df_resampled["date"]],
                "values": df_resampled["value"].tolist()
            }
            print(f"    → Stored {len(df_resampled)} data points")
    
    # Calculate overall grade
    json_data["current"]["overall_grade"] = calculate_overall_grade(grades)
    
    # Add summary description
    overall = json_data["current"]["overall_grade"]
    json_data["current"]["summary"] = get_summary_description(overall["grade"])
    
    # Sanitize for JSON
    json_data = sanitize_for_json(json_data)
    
    # Save to file
    if output_path:
        save_json(json_data, output_path, indent=config.get("output", {}).get("indent", 2))
    
    return json_data


def get_summary_description(grade: str) -> str:
    """Get summary description based on overall grade."""
    descriptions = {
        "A+": "Economic growth indicators are showing excellent strength across all measures.",
        "A": "Economic growth indicators are very positive with strong performance.",
        "B": "Economic growth indicators are showing moderate expansion.",
        "C": "Economic growth indicators are showing mixed signals with some concerns.",
        "D": "Economic growth indicators are showing weakness across multiple measures.",
        "N/A": "Insufficient data to assess economic growth conditions."
    }
    return descriptions.get(grade, "Economic growth indicators are being monitored.")


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Export Growth & Output economic indicators to JSON"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="growth_output.json",
        help="Output JSON file path (default: growth_output.json)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Config YAML file path"
    )
    
    args = parser.parse_args()
    
    try:
        export_growth_output_json(
            output_path=args.output,
            config_path=args.config
        )
        print("\n✓ Growth & Output data export complete!")
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
