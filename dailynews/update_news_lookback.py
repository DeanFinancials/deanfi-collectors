"""\
Update rolling daily-news lookback files in the deanfi-data working tree.

This is designed to run inside the `daily-news.yml` workflow after the point-in-time
news snapshots are generated.

It keeps one entry per ET calendar date and retains only the most recent N dates.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update daily-news lookback JSON files")
    parser.add_argument(
        "--data-repo-path",
        required=True,
        help="Path to the checked-out deanfi-data repo (e.g. data-cache)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="How many ET dates to retain (default: 7)",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def normalize_history(existing: dict | list | None) -> list[dict]:
    if not existing:
        return []

    if isinstance(existing, dict):
        data = existing.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict) and isinstance(row.get("market_date"), str)]

    if isinstance(existing, list):
        return [row for row in existing if isinstance(row, dict) and isinstance(row.get("market_date"), str)]

    return []


def upsert_by_market_date(history: list[dict], entry: dict) -> list[dict]:
    md = entry.get("market_date")
    if not isinstance(md, str) or not md:
        return history
    out: list[dict] = [row for row in history if row.get("market_date") != md]
    out.append(entry)
    out.sort(key=lambda r: r.get("market_date", ""))
    return out


def trim_to_last_n_dates(history: list[dict], n: int) -> list[dict]:
    if n <= 0:
        return []
    unique_dates = sorted({row.get("market_date") for row in history if isinstance(row.get("market_date"), str)})
    keep = set(unique_dates[-n:])
    return [row for row in history if row.get("market_date") in keep]


def main() -> None:
    args = parse_args()
    data_repo_path = Path(args.data_repo_path)
    lookback_days = int(args.lookback_days)

    et_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()

    # Inputs from collectors working tree
    top_news_now = load_json(Path(__file__).parent / "top_news.json") or {}
    sector_news_now = load_json(Path(__file__).parent / "sector_news.json") or {}

    # Outputs in data repo working tree
    out_dir = data_repo_path / "daily-news"
    top_hist_path = out_dir / "top_news_lookback.json"
    sector_hist_path = out_dir / "sector_news_lookback.json"

    existing_top = normalize_history(load_json(top_hist_path))
    existing_sector = normalize_history(load_json(sector_hist_path))

    top_entry = {
        "market_date": et_today,
        "generated_at": generated_at,
        "source_file_generated_at": (top_news_now.get("metadata") or {}).get("generated_at"),
        "articles": top_news_now.get("articles") or top_news_now.get("data") or [],
    }

    sector_entry = {
        "market_date": et_today,
        "generated_at": generated_at,
        "source_file_generated_at": (sector_news_now.get("metadata") or {}).get("generated_at"),
        "sectors": sector_news_now.get("sectors") or sector_news_now.get("data") or {},
    }

    top_history = trim_to_last_n_dates(upsert_by_market_date(existing_top, top_entry), lookback_days)
    sector_history = trim_to_last_n_dates(upsert_by_market_date(existing_sector, sector_entry), lookback_days)

    write_json(
        top_hist_path,
        {
            "metadata": {
                "generated_at": generated_at,
                "timezone": "America/New_York",
                "lookback_days": lookback_days,
                "description": "Rolling lookback of daily top news snapshots (one entry per ET date)",
            },
            "data": top_history,
        },
    )
    write_json(
        sector_hist_path,
        {
            "metadata": {
                "generated_at": generated_at,
                "timezone": "America/New_York",
                "lookback_days": lookback_days,
                "description": "Rolling lookback of daily sector news snapshots (one entry per ET date)",
            },
            "data": sector_history,
        },
    )


if __name__ == "__main__":
    main()
