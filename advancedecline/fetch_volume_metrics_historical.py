"""\
Fetch Historical Advancing/Declining Volume Metrics for S&P 500

This produces a compact rolling time series used for Market Pulse lookbacks.

Why this exists:
- We already store A/D (advances/declines), highs/lows, and % above MAs as
  historical series in deanfi-data.
- Daily volume breadth is only available in the point-in-time daily snapshot.
  A small rolling series lets Market Pulse build 5-session lookbacks.

Data source: Yahoo Finance (yfinance)
Output: volume_metrics_historical.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.cache_manager import CachedDataFetcher
from shared.spx_universe import fetch_spx_tickers


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch historical volume breadth time series")
    parser.add_argument("--cache-dir", type=str, default=None, help="Cache directory for parquet files")
    parser.add_argument(
        "--sessions",
        type=int,
        default=30,
        help="How many most-recent trading sessions to emit (default: 30)",
    )
    return parser.parse_args()


def download_market_data(tickers: list[str], *, period: str, cache_dir: str | None) -> pd.DataFrame:
    if cache_dir:
        fetcher = CachedDataFetcher(cache_dir=cache_dir)
        return fetcher.fetch_prices(tickers=tickers, period=period, cache_name="spx_volume_breadth")

    import yfinance as yf

    return yf.download(tickers, period=period, progress=False, auto_adjust=True, threads=True)


def build_volume_metrics_series(data: pd.DataFrame, *, sessions: int) -> list[dict]:
    if not isinstance(data, pd.DataFrame) or data.empty:
        return []

    if not isinstance(data.columns, pd.MultiIndex):
        # Expected multi-index: (field, ticker)
        return []

    if "Close" not in data.columns.levels[0] or "Volume" not in data.columns.levels[0]:
        return []

    close_prices = data["Close"]
    volumes = data["Volume"]

    if close_prices.shape[0] < 2:
        return []

    # We need i-1 for comparisons, so we start at 1.
    start_idx = max(1, close_prices.shape[0] - sessions)
    rows: list[dict] = []

    for i in range(start_idx, close_prices.shape[0]):
        close_today = close_prices.iloc[i]
        close_prev = close_prices.iloc[i - 1]
        vol_today = volumes.iloc[i]

        daily_change = close_today - close_prev
        advancing_mask = daily_change > 0
        declining_mask = daily_change < 0

        advancing_volume = float(vol_today[advancing_mask].sum(skipna=True))
        declining_volume = float(vol_today[declining_mask].sum(skipna=True))
        total_volume = float(vol_today.sum(skipna=True))

        date = close_prices.index[i]
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)

        rows.append(
            {
                "date": date_str,
                "advancing_volume": int(advancing_volume),
                "declining_volume": int(declining_volume),
                "total_volume": int(total_volume),
                "volume_ratio": round(advancing_volume / declining_volume, 3) if declining_volume > 0 else None,
                "advancing_volume_pct": round((advancing_volume / total_volume) * 100, 2) if total_volume > 0 else 0,
            }
        )

    return rows


def main() -> None:
    args = parse_args()
    config = load_config()

    tickers = fetch_spx_tickers()
    period = config.get("download_period", "2y")

    data = download_market_data(tickers, period=period, cache_dir=args.cache_dir)
    series = build_volume_metrics_series(data, sessions=max(2, int(args.sessions)))

    output = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": config.get("data_source", "Yahoo Finance (yfinance)"),
            "universe": config.get("universe", "S&P 500"),
            "total_stocks_analyzed": len(tickers),
            "sessions_emitted": len(series),
            "description": "Rolling advancing/declining volume metrics for market breadth lookbacks",
        },
        "field_descriptions": {
            "date": "Trading date (YYYY-MM-DD)",
            "advancing_volume": "Sum of volumes for stocks up vs prior close",
            "declining_volume": "Sum of volumes for stocks down vs prior close",
            "total_volume": "Sum of volumes for all stocks in universe",
            "volume_ratio": "advancing_volume / declining_volume",
            "advancing_volume_pct": "advancing_volume / total_volume * 100",
        },
        "data": series,
    }

    output_file = Path(__file__).parent / config["output_files"]["volume_metrics_historical"]
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✓ Volume metrics historical saved to {output_file}", file=sys.stderr)
    if series:
        print(f"  Latest date: {series[-1]['date']}", file=sys.stderr)


if __name__ == "__main__":
    main()
