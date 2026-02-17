#!/usr/bin/env python3
"""
Export Consumer & Credit economic indicators to JSON.
Includes: Sentiment, retail spending, saving rate, and consumer credit balances.
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
    calculate_percentile_rank,
    calculate_grade,
    calculate_overall_grade,
    calculate_trend,
    is_trend_favorable,
    calculate_change_metrics,
    adaptive_resample,
    sanitize_for_json,
)
from economy_io import load_config, save_json


def export_consumer_credit_json(output_path: str, config_path: str = None, override_history_days: int = None) -> dict:
    """Generate Consumer & Credit indicators JSON."""
    config = load_config(config_path)
    fred = FREDClient(rate_limit=config.get("fred", {}).get("rate_limit_seconds", 0.1))
    indicators = get_indicators_by_category("consumer_credit")

    # Use 20 years of history for consistency with other economy collectors
    if override_history_days:
        history_days = override_history_days
    else:
        history_days = 7300  # 20 years

    end_date = datetime.now()
    start_date = end_date - timedelta(days=history_days)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    print(f"Fetching Consumer & Credit data from {start_date_str} to {end_date_str}...")
    print("  (20-year lookback for robust percentile calculations)")

    indicator_data = {}
    for indicator in indicators:
        if indicator.is_derived:
            continue
        print(f"  Fetching {indicator.series_id} ({indicator.name})...")
        try:
            df = fred.get_series_range(indicator.series_id, start_date_str, end_date_str)
            indicator_data[indicator.series_id] = df
        except Exception as fetch_error:
            # Log and continue so a single series failure doesn't abort the export.
            print(f"  Warning: Failed to fetch {indicator.series_id}: {fetch_error}")

            # Fallback: For Conference Board Consumer Confidence, try OECD consumer confidence as backup.
            if indicator.series_id == "CONCCONF":
                fallback_id = "CSCICP03USM665S"  # OECD Consumer Confidence Index for US
                print(f"  Attempting fallback series {fallback_id} (OECD Consumer Confidence)...")
                try:
                    df_fallback = fred.get_series_range(fallback_id, start_date_str, end_date_str)
                    indicator_data[indicator.series_id] = df_fallback
                    print(f"  Fallback {fallback_id} fetched successfully")
                except Exception as fallback_error:
                    print(f"  Warning: Fallback {fallback_id} also failed: {fallback_error}")
                    indicator_data[indicator.series_id] = None
            else:
                indicator_data[indicator.series_id] = None

    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)

    readme = {
        "title": "Consumer & Credit Dashboard",
        "description": "Consumer sentiment, spending, saving, and credit balance indicators from FRED with percentile grading.",
        "purpose": "Track household demand strength and credit conditions for macro monitoring and risk dashboards.",
        "metrics_explained": {
            "UMCSENT": {
                "description": "University of Michigan consumer sentiment (headline index).",
                "interpretation": "Higher sentiment signals confidence in spending and income outlook."
            },
            "CONCCONF": {
                "description": "Conference Board consumer confidence (1985=100). Fallback to OECD consumer confidence when unavailable.",
                "interpretation": "Higher readings align with stronger consumer demand; persistent drops can precede spending slowdowns."
            },
            "RSAFS": {
                "description": "Advance retail and food services sales (nominal, SA).",
                "interpretation": "Higher nominal sales show demand breadth; monitor alongside real sales for inflation effects."
            },
            "RRSFS": {
                "description": "Real retail and food services sales (inflation-adjusted, SA).",
                "interpretation": "Real growth confirms volume strength beyond price effects; weakness can flag demand softening."
            },
            "RSXFS": {
                "description": "Retail sales excluding motor vehicles and parts (nominal, SA).",
                "interpretation": "Strips autos to gauge core discretionary demand; trends often smoother than headline retail."
            },
            "PCE": {
                "description": "Personal consumption expenditures (nominal, SAAR).",
                "interpretation": "Broad nominal spending; rising values indicate stronger aggregate demand."
            },
            "PCEC96": {
                "description": "Real personal consumption expenditures (chained 2017 dollars, SAAR).",
                "interpretation": "Volume-based view of consumption; key for GDP contribution and real demand strength."
            },
            "PSAVERT": {
                "description": "Personal saving rate (% of disposable income, SA).",
                "interpretation": "Higher saving improves resilience but can coincide with slower spending; very low levels reduce cushion."
            },
            "TOTALSL": {
                "description": "Total consumer credit outstanding (SA).",
                "interpretation": "Neutral by default; rapid growth can imply rising leverage, contraction can imply tightening or deleveraging."
            },
            "REVOLSL": {
                "description": "Revolving consumer credit (credit cards, SA).",
                "interpretation": "Rising balances may reflect confidence or stress; watch alongside delinquency metrics."
            },
            "NONREVSL": {
                "description": "Nonrevolving consumer credit (installment/auto/student, SA).",
                "interpretation": "Growth signals credit expansion; slowing or declines can reflect tighter lending or reduced demand."
            },
            "BAMLH0A0HYM2": {
                "description": "ICE BofA US High Yield Index option-adjusted spread (OAS, daily).",
                "interpretation": "Lower spreads indicate easier credit and lower risk premiums; sharp widening typically signals rising credit stress and risk-off conditions."
            }
        },
        "trading_applications": {
            "consumer_equities": "Pair sentiment and real sales trends with sector earnings to gauge demand sensitivity.",
            "credit_risk": "Use revolving/nonrevolving growth vs saving rate as a quick leverage/stress pulse for consumer credit exposure; use high-yield OAS for market-implied credit stress confirmation."
        },
        "notes": {
            "history_window": "20-year history (7300 days) for percentile grading.",
            "fallbacks": "CONCCONF falls back to OECD consumer confidence (CSCICP03USM665S) if unavailable.",
            "resampling": "Series are adaptively resampled per frequency before storing history."
        }
    }

    json_data = {
        "_README": readme,
        "metadata": {
            "generated_at": now.isoformat(),
            "data_source": "FRED API",
            "category": "Consumer & Credit",
            "indicators": [
                {
                    "series_id": ind.series_id,
                    "name": ind.name,
                    "frequency": ind.frequency,
                    "unit": ind.unit,
                }
                for ind in indicators
            ],
            "history_days": history_days,
            "data_start": start_date_str,
            "data_end": end_date_str,
        },
        "current": {"date": None, "overall_grade": {}, "indicators": {}},
        "history": {"series": {}},
    }

    grades = []

    for indicator in indicators:
        series_id = indicator.series_id
        if series_id not in indicator_data or indicator_data[series_id] is None or indicator_data[series_id].empty:
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
            "name": indicator.name,
            "value": round(current_value, 2) if current_value else None,
            "unit": indicator.unit,
            "frequency": indicator.frequency,
            "percentile": percentile,
            "grade": grade,
            "trend": trend,
            "is_favorable": is_favorable,
            "changes": changes,
            "interpretation": indicator.interpretation,
        }

        print(f"  Resampling {series_id} ({indicator.frequency} → storage format)...")
        df_resampled = adaptive_resample(df_clean, indicator.frequency, series_id)

        if not df_resampled.empty:
            json_data["history"]["series"][series_id] = {
                "dates": [d.strftime("%Y-%m-%d") for d in df_resampled["date"]],
                "values": df_resampled["value"].tolist(),
            }
            print(f"    → Stored {len(df_resampled)} data points")

    json_data["current"]["overall_grade"] = calculate_overall_grade(grades)
    json_data["current"]["summary"] = get_summary_description(json_data["current"]["overall_grade"].get("grade", "N/A"))
    json_data = sanitize_for_json(json_data)

    if output_path:
        save_json(json_data, output_path, indent=config.get("output", {}).get("indent", 2))

    return json_data


def get_summary_description(grade: str) -> str:
    """Get summary description based on overall grade."""
    descriptions = {
        "A+": "Consumer demand and credit conditions are exceptionally strong across sentiment, spending, and balances.",
        "A": "Consumer indicators are very healthy with broad strength in demand and credit conditions.",
        "B": "Consumer indicators are generally supportive with steady demand and manageable credit trends.",
        "C": "Consumer indicators are mixed; watch for shifts in spending, savings, or credit stress.",
        "D": "Consumer indicators are weak or deteriorating across sentiment, spending, and credit.",
        "N/A": "Insufficient data to assess consumer and credit conditions.",
    }
    return descriptions.get(grade, "Consumer and credit indicators are being monitored.")


def main():
    parser = argparse.ArgumentParser(description="Export Consumer & Credit indicators to JSON")
    parser.add_argument("--output", type=str, default="consumer_credit.json")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    try:
        export_consumer_credit_json(args.output, args.config)
        print("\n✓ Consumer & Credit data export complete!")
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
