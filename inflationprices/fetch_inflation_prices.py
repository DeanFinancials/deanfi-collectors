#!/usr/bin/env python3
"""
Export Inflation & Prices economic indicators to JSON.
Includes: CPI, Core CPI, PCE, Core PCE, PPI, Breakeven Inflation, Energy Prices
"""
import argparse
import sys
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
    calculate_percentile_rank, calculate_grade, calculate_overall_grade,
    calculate_trend, is_trend_favorable, calculate_change_metrics, adaptive_resample, sanitize_for_json
)
from economy_io import load_config, save_json


def export_inflation_prices_json(output_path: str, config_path: str = None, override_history_days: int = None) -> dict:
    """Generate Inflation & Prices indicators JSON."""
    config = load_config(config_path)
    fred = FREDClient(rate_limit=config.get("fred", {}).get("rate_limit_seconds", 0.1))
    indicators = get_indicators_by_category("inflation_prices")
    
    # V2: 20 years of history
    if override_history_days:
        history_days = override_history_days
    else:
        history_days = 7300  # 20 years
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=history_days)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Fetching Inflation & Prices data from {start_date_str} to {end_date_str}...")
    print(f"  (20-year lookback for robust percentile calculations)")
    
    indicator_data = {}
    for indicator in indicators:
        if indicator.is_derived:
            continue
        print(f"  Fetching {indicator.series_id} ({indicator.name})...")
        df = fred.get_series_range(indicator.series_id, start_date_str, end_date_str)
        indicator_data[indicator.series_id] = df
    
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)
    
    json_data = {
        "metadata": {
            "generated_at": now.isoformat(),
            "data_source": "FRED API",
            "category": "Inflation & Prices",
            "indicators": [{"series_id": ind.series_id, "name": ind.name, "frequency": ind.frequency, "unit": ind.unit}
                          for ind in indicators],
            "history_days": history_days,
            "data_start": start_date_str,
            "data_end": end_date_str
        },
        "current": {"date": None, "overall_grade": {}, "indicators": {}},
        "history": {"series": {}}
    }
    
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
        
        current_value = df_clean.iloc[-1]["value"]
        current_date = df_clean.iloc[-1]["date"]
        previous_value = df_clean.iloc[-2]["value"] if len(df_clean) > 1 else current_value
        
        historical_values = df_clean["value"]
        percentile = calculate_percentile_rank(historical_values, current_value)
        grade = calculate_grade(percentile, indicator.interpretation)
        grades.append(grade)
        trend = calculate_trend(current_value, previous_value)
        is_favorable = is_trend_favorable(trend, indicator.interpretation)
        changes = calculate_change_metrics(df_clean, frequency=indicator.frequency)
        
        if json_data["current"]["date"] is None:
            json_data["current"]["date"] = current_date.strftime("%Y-%m-%d")
        
        json_data["current"]["indicators"][series_id] = {
            "name": indicator.name, "value": round(current_value, 2) if current_value else None,
            "unit": indicator.unit, "frequency": indicator.frequency, "percentile": percentile,
            "grade": grade, "trend": trend, "is_favorable": is_favorable, "changes": changes, "interpretation": indicator.interpretation
        }
        
        print(f"  Resampling {series_id} ({indicator.frequency} → storage format)...")
        df_resampled = adaptive_resample(df_clean, indicator.frequency, series_id)
        
        if not df_resampled.empty:
            json_data["history"]["series"][series_id] = {
                "dates": [d.strftime("%Y-%m-%d") for d in df_resampled["date"]],
                "values": df_resampled["value"].tolist()
            }
            print(f"    → Stored {len(df_resampled)} data points")
    
    json_data["current"]["overall_grade"] = calculate_overall_grade(grades)
    json_data["current"]["summary"] = get_summary_description(json_data["current"]["overall_grade"]["grade"])
    json_data = sanitize_for_json(json_data)
    
    if output_path:
        save_json(json_data, output_path, indent=config.get("output", {}).get("indent", 2))
    
    return json_data


def get_summary_description(grade: str) -> str:
    descriptions = {
        "A+": "Inflation readings are well within optimal target ranges across all measures.",
        "A": "Inflation metrics are healthy and near target levels.",
        "B": "Inflation levels are acceptable but warrant monitoring.",
        "C": "Inflation pressures are building and require attention.",
        "D": "Inflation is significantly elevated or problematically low.",
        "N/A": "Insufficient data to assess inflation conditions."
    }
    return descriptions.get(grade, "Inflation indicators are being monitored.")


def main():
    parser = argparse.ArgumentParser(description="Export Inflation & Prices indicators to JSON")
    parser.add_argument("--output", type=str, default="inflation_prices.json")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    
    try:
        export_inflation_prices_json(args.output, args.config)
        print("\n✓ Inflation & Prices data export complete!")
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
