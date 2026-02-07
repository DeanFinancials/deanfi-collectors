#!/usr/bin/env python3
"""ETF fund flows collector.

Derives daily ETF flows from AUM and return factors:
  Flow_t = AUM_t - (AUM_{t-1} * return_factor_t)

Primary return factor: NAV_t / NAV_{t-1}
Secondary return factor (optional): Close_t / Close_{t-1}

Writes month-partitioned JSON outputs and aggregate rollups.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import yfinance as yf
import yaml


@dataclass(frozen=True)
class UniverseRow:
    ticker: str
    asset_class: str
    category: str
    subcategory: str
    notes: str


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}
    return config


def load_universe(csv_path: str, columns: Dict[str, str], exclude: Iterable[str]) -> List[UniverseRow]:
    exclude_set = {t.strip().upper() for t in exclude if t}
    rows: List[UniverseRow] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            ticker = (raw.get(columns["ticker"]) or "").strip().upper()
            if not ticker or ticker in exclude_set:
                continue
            rows.append(
                UniverseRow(
                    ticker=ticker,
                    asset_class=(raw.get(columns["asset_class"]) or "").strip(),
                    category=(raw.get(columns["category"]) or "").strip(),
                    subcategory=(raw.get(columns["subcategory"]) or "").strip(),
                    notes=(raw.get(columns.get("notes", "Notes")) or "").strip(),
                )
            )

    # stable ordering
    rows.sort(key=lambda r: r.ticker)
    return rows


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_iso_date(d: str) -> Optional[date]:
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def find_latest_completed_session(prices_df) -> Optional[date]:
    """Given a yfinance daily history dataframe with a DatetimeIndex, find the latest date with a Close."""
    if prices_df is None or prices_df.empty:
        return None

    try:
        # Works for both single and multi-index columns
        if "Close" in prices_df.columns:
            close = prices_df["Close"]
        else:
            # multi-index: ('Close', ticker)
            close = prices_df.xs("Close", axis=1, level=0)

        # for multi-ticker, consider any ticker having close
        if hasattr(close, "dropna"):
            close_any = close.dropna(how="all") if getattr(close, "ndim", 1) > 1 else close.dropna()
            if close_any.empty:
                return None
            idx = close_any.index
            last_ts = idx.max()
            return last_ts.date() if hasattr(last_ts, "date") else None

    except Exception:
        return None

    return None


def yfinance_fetch_closes(tickers: List[str], start: date, end: date) -> Dict[str, Dict[str, float]]:
    """Fetch daily close prices from yfinance for tickers in [start, end].

    Returns dict: {ticker: {YYYY-MM-DD: close}}
    """
    if not tickers:
        return {}

    # yfinance can struggle with very large ticker lists; batch defensively.
    batch_size = 125
    result: Dict[str, Dict[str, float]] = {t: {} for t in tickers}

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        df = yf.download(
            tickers=batch,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            group_by="column",
            auto_adjust=False,
            threads=True,
            progress=False,
        )

        if df is None or df.empty:
            continue

        # MultiIndex columns path (Field, Ticker) — works for 1+ tickers.
        try:
            close_df = df.xs("Close", axis=1, level=0)
            if getattr(close_df, "ndim", 1) == 1:
                # Single ticker: Series of closes
                s = close_df.dropna()
                t_sym = str(getattr(close_df, "name", batch[0]) or batch[0]).upper()
                if t_sym not in result:
                    result[t_sym] = {}
                for ts, val in s.items():
                    result[t_sym][ts.date().isoformat()] = float(val)
            else:
                for ticker in close_df.columns:
                    s = close_df[ticker].dropna()
                    t_sym = str(ticker).upper()
                    if t_sym not in result:
                        result[t_sym] = {}
                    for ts, val in s.items():
                        result[t_sym][ts.date().isoformat()] = float(val)
            continue
        except Exception:
            pass

        # Non-MultiIndex columns path
        if "Close" not in df.columns:
            continue

        close_obj = df["Close"]
        if getattr(close_obj, "ndim", 1) > 1:
            # DataFrame of closes
            if len(batch) == 1 and len(getattr(close_obj, "columns", [])) == 1:
                s = close_obj.iloc[:, 0].dropna()
                for ts, val in s.items():
                    result[batch[0]][ts.date().isoformat()] = float(val)
            else:
                for ticker in close_obj.columns:
                    s = close_obj[ticker].dropna()
                    t_sym = str(ticker).upper()
                    if t_sym not in result:
                        result[t_sym] = {}
                    for ts, val in s.items():
                        result[t_sym][ts.date().isoformat()] = float(val)
        else:
            # Series of closes
            s = close_obj.dropna()
            for ts, val in s.items():
                result[batch[0]][ts.date().isoformat()] = float(val)

    return result


def _epoch_to_utc_iso(epoch_seconds: Any) -> Optional[str]:
    if epoch_seconds is None:
        return None
    try:
        return datetime.utcfromtimestamp(int(epoch_seconds)).replace(microsecond=0).isoformat() + "Z"
    except Exception:
        return None


def yfinance_etf_aum_nav(symbol: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Fetch AUM/NAV for an ETF from yfinance Ticker.info.

    Known useful keys for ETFs (availability varies by ticker):
      - totalAssets (AUM/net assets)
      - navPrice (NAV)
      - regularMarketTime (epoch seconds)
    """
    try:
        info = yf.Ticker(symbol).get_info()
    except Exception as e:
        print(f"[warn] yfinance info request failed for {symbol}: {e}", file=sys.stderr)
        return None, None, None

    if not isinstance(info, dict):
        return None, None, None

    aum = safe_float(info.get("totalAssets"))
    nav = safe_float(info.get("navPrice"))
    updated_at = _epoch_to_utc_iso(info.get("regularMarketTime"))
    return aum, nav, updated_at


def alphavantage_etf_profile(symbol: str, api_key: str, timeout_seconds: int) -> Optional[dict]:
    """Fetch Alpha Vantage ETF_PROFILE payload.

    Free-tier daily cap is very low; keep calls to a minimum.
    """
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "ETF_PROFILE", "symbol": symbol, "apikey": api_key},
            timeout=timeout_seconds,
        )
        if r.status_code != 200:
            print(f"[warn] Alpha Vantage HTTP {r.status_code} for {symbol}", file=sys.stderr)
            return None
        payload = r.json()
        # Rate-limit / entitlement style error payloads
        if isinstance(payload, dict) and ("Information" in payload or "Note" in payload or "Error Message" in payload):
            msg = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
            print(f"[warn] Alpha Vantage response for {symbol}: {msg}", file=sys.stderr)
            return None
        return payload if isinstance(payload, dict) else None
    except Exception as e:
        print(f"[warn] Alpha Vantage request failed for {symbol}: {e}", file=sys.stderr)
        return None


def fetch_aum_nav_with_fallbacks(
    symbol: str,
    source_order: List[str],
    yfinance_sleep_seconds: float,
    alpha_cfg: dict,
    alpha_key: str,
    call_counts: Dict[str, int],
    cap_applied: Dict[str, bool],
) -> Tuple[Optional[float], Optional[float], Optional[str], str, List[str]]:
    """Return (aum, nav, updated_at, source, warnings).

    Notes:
      - yfinance can return both AUM (totalAssets) and NAV (navPrice).
      - Alpha Vantage ETF_PROFILE provides net_assets (AUM) but may not provide NAV.
    """
    warnings: List[str] = []
    for source in source_order:
        s = (source or "").strip().lower()
        if s in ("yf", "yahoo", "yfinance"):
            if yfinance_sleep_seconds > 0:
                time.sleep(yfinance_sleep_seconds)
            aum, nav, updated_at = yfinance_etf_aum_nav(symbol)
            if aum is not None or nav is not None:
                return aum, nav, updated_at, "yfinance", warnings
            warnings.append("yfinance_missing_aum_and_nav")
            continue

        if s in ("alphavantage", "alpha_vantage", "av"):
            if not alpha_key:
                warnings.append("alphavantage_missing_api_key")
                continue
            max_calls = int(alpha_cfg.get("max_calls_per_run", 25))
            if call_counts.get("alphavantage", 0) >= max_calls:
                cap_applied["alphavantage"] = True
                warnings.append("alphavantage_call_cap_reached")
                continue

            sleep_between = float(alpha_cfg.get("sleep_seconds_between_calls", 15))
            if sleep_between > 0:
                time.sleep(sleep_between)

            payload = alphavantage_etf_profile(symbol, alpha_key, int(alpha_cfg.get("timeout_seconds", 20)))
            call_counts["alphavantage"] = call_counts.get("alphavantage", 0) + 1
            if not payload:
                continue
            aum = safe_float(payload.get("net_assets"))
            updated_at = _utc_now_iso()
            if aum is not None:
                # Alpha Vantage ETF_PROFILE does not reliably include a NAV field.
                return aum, None, updated_at, "alphavantage", warnings
            continue

        warnings.append(f"unknown_aum_nav_source:{source}")

    return None, None, None, "none", warnings


def read_monthly_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_monthly_json(path: Path, payload: dict, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=indent, ensure_ascii=False)


def upsert_daily_point(daily: List[dict], point: dict) -> List[dict]:
    """Idempotently upsert by date."""
    target_date = point.get("date")
    kept = [p for p in daily if p.get("date") != target_date]
    kept.append(point)
    kept.sort(key=lambda x: x.get("date", ""))
    return kept


def get_prev_point(
    current_month_doc: dict,
    prev_month_doc: Optional[dict],
    ticker: str,
    session_date: str,
) -> Optional[dict]:
    """Get previous available point for ticker, searching current month then previous month."""
    def points_from(doc: Optional[dict]) -> List[dict]:
        if not doc:
            return []
        return (((doc.get("data") or {}).get(ticker) or {}).get("daily") or [])

    # Search in current month for latest date < session_date
    current_points = points_from(current_month_doc)
    prev = [p for p in current_points if (p.get("date") or "") < session_date]
    if prev:
        return sorted(prev, key=lambda x: x.get("date", ""))[-1]

    # Fall back to previous month doc
    prev_points = points_from(prev_month_doc)
    prev2 = [p for p in prev_points if (p.get("date") or "") < session_date]
    if prev2:
        return sorted(prev2, key=lambda x: x.get("date", ""))[-1]

    return None


def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def compute_flow(aum_t: Optional[float], aum_prev: Optional[float], r_t: Optional[float]) -> Optional[float]:
    if aum_t is None or aum_prev is None or r_t is None:
        return None
    return aum_t - (aum_prev * r_t)


def build_readme_block() -> dict:
    return {
        "title": "ETF Fund Flows (Derived)",
        "description": "Daily derived ETF flow estimates per ticker (AUM/NAV + return adjustment).",
        "purpose": "Track daily creation/redemption activity (fund flows) and aggregate by asset class/category/subcategory.",
        "methodology": {
            "overview": "Flows are derived by isolating changes in AUM not explained by market performance.",
            "primary_formula": "Flow_t = AUM_t - (AUM_{t-1} * (NAV_t/NAV_{t-1}))",
            "secondary_formula": "Flow_t_close = AUM_t - (AUM_{t-1} * (Close_t/Close_{t-1}))",
            "notes": [
                "AUM and NAV are sourced from yfinance when available (Ticker.info keys: totalAssets, navPrice).",
                "Close prices are sourced from yfinance in a batched request to minimize API calls.",
                "Optional fallbacks can be configured (e.g., Alpha Vantage ETF_PROFILE provides net_assets).",
                "Differences vs paid providers can occur (NAV vs close basis, corporate actions, smoothing around holidays).",
            ],
        },
    }


def aggregate_points(points: List[dict], key_name: str) -> dict:
    """Aggregate flows by a label per point (asset_class/category/subcategory).

    Expects point to include:
      - date
      - label field (key_name)
      - flow_nav (primary)
      - flow_close (secondary)
      - aum
    """
    by_date: Dict[str, Dict[str, dict]] = {}

    for p in points:
        d = p.get("date")
        label = p.get(key_name) or "Unknown"
        if not d:
            continue

        bucket = by_date.setdefault(d, {})
        agg = bucket.setdefault(
            label,
            {
                "aum": 0.0,
                "flow_nav": 0.0,
                "flow_close": 0.0,
                "tickers": 0,
                "tickers_with_aum": 0,
                "tickers_with_flow_nav": 0,
                "tickers_with_flow_close": 0,
            },
        )

        aum = safe_float(p.get("aum"))
        flow_nav = safe_float(p.get("flow_nav"))
        flow_close = safe_float(p.get("flow_close"))

        if aum is not None:
            agg["aum"] += aum
            agg["tickers_with_aum"] += 1

        agg["tickers"] += 1

        if flow_nav is not None:
            agg["flow_nav"] += flow_nav
            agg["tickers_with_flow_nav"] += 1

        if flow_close is not None:
            agg["flow_close"] += flow_close
            agg["tickers_with_flow_close"] += 1

    # If nothing contributed for a metric, emit null instead of 0.0
    for _d, groups in by_date.items():
        for _label, agg in groups.items():
            if agg.get("tickers_with_aum", 0) == 0:
                agg["aum"] = None
            if agg.get("tickers_with_flow_nav", 0) == 0:
                agg["flow_nav"] = None
            if agg.get("tickers_with_flow_close", 0) == 0:
                agg["flow_close"] = None

    out = []
    for d in sorted(by_date.keys()):
        out.append({"date": d, "groups": by_date[d]})
    return {"daily": out}


def upsert_agg_daily(daily: List[dict], date_str: str, groups: dict) -> List[dict]:
    kept = [p for p in daily if p.get("date") != date_str]
    kept.append({"date": date_str, "groups": groups})
    kept.sort(key=lambda x: x.get("date", ""))
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="./config.yml", help="Path to config.yml")
    ap.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated tickers for testing (overrides CSV universe)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit to first N tickers (useful for testing)",
    )
    ap.add_argument(
        "--session-date",
        default="",
        help="Force session date YYYY-MM-DD (default: latest completed session from yfinance)",
    )
    args = ap.parse_args()

    config = load_config(args.config)

    aum_nav_cfg = config.get("aum_nav") or {}
    source_order = aum_nav_cfg.get("source_order") or ["yfinance"]
    if not isinstance(source_order, list) or not source_order:
        source_order = ["yfinance"]

    yfinance_cfg = aum_nav_cfg.get("yfinance") or {}
    yfinance_sleep_seconds = float(yfinance_cfg.get("sleep_seconds_per_ticker", 0))

    alpha_cfg = (config.get("api") or {}).get("alphavantage") or {}
    alpha_env = alpha_cfg.get("api_key_env", "ALPHA_VANTAGE_API_KEY")
    alpha_key = os.environ.get(alpha_env, "").strip()

    universe_cfg = config.get("universe") or {}
    csv_path = universe_cfg.get("csv_path", "../organized_etf_list.csv")
    columns = universe_cfg.get("columns") or {}
    exclude = universe_cfg.get("exclude_tickers") or []

    output_cfg = config.get("output") or {}
    out_dir = Path(output_cfg.get("directory", "./output"))
    indent = int(output_cfg.get("indent", 2))

    per_ticker_prefix = output_cfg.get("per_ticker_prefix", "etf_fund_flows")

    aggregates_cfg = (output_cfg.get("aggregates") or {})
    aggregates_enabled = bool(aggregates_cfg.get("enabled", True))

    # Determine ticker universe
    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        universe_rows = [UniverseRow(t, "", "", "", "") for t in tickers]
    else:
        universe_rows = load_universe(csv_path, columns, exclude)

        # default to test_tickers on manual runs if user passes limit=0? no.
        # We'll only use test_tickers if user explicitly provides --limit or --tickers.

    if args.limit and args.limit > 0:
        universe_rows = universe_rows[: args.limit]

    tickers = [r.ticker for r in universe_rows]

    if not tickers:
        print("No tickers to process.", file=sys.stderr)
        return 0

    call_counts: Dict[str, int] = {"alphavantage": 0}
    cap_applied: Dict[str, bool] = {"alphavantage": False}

    # Fetch yfinance closes for a small window for all tickers (batched)
    prices_cfg = (config.get("prices") or {}).get("yfinance") or {}
    lookback_days = int(prices_cfg.get("lookback_calendar_days", 10))

    forced_session = parse_iso_date(args.session_date)
    if forced_session:
        session_dt = forced_session
        start_dt = session_dt - timedelta(days=lookback_days)
        end_dt = session_dt
    else:
        # Pull the last ~10 calendar days so we can locate the latest completed session.
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=lookback_days)

    closes_by_ticker = yfinance_fetch_closes(tickers, start_dt, end_dt)

    if forced_session:
        session_date_str = session_dt.isoformat()
    else:
        # Find latest completed session from the downloaded data.
        # Use any ticker that has data.
        sample_df = yf.download(
            tickers=tickers[: min(10, len(tickers))],
            start=start_dt.isoformat(),
            end=(end_dt + timedelta(days=1)).isoformat(),
            interval="1d",
            group_by="column",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
        session_dt = find_latest_completed_session(sample_df)
        if not session_dt:
            print("No completed session detected from yfinance data (holiday/weekend?).", file=sys.stderr)
            return 0
        session_date_str = session_dt.isoformat()

    # Load current month doc and previous month doc
    mkey = month_key(session_dt)
    cur_path = out_dir / f"{per_ticker_prefix}_{mkey}.json"

    prev_month_dt = (session_dt.replace(day=1) - timedelta(days=1))
    prev_mkey = month_key(prev_month_dt)
    prev_path = out_dir / f"{per_ticker_prefix}_{prev_mkey}.json"

    cur_doc = read_monthly_json(cur_path) or {
        "_README": build_readme_block(),
        "metadata": {
            "month": mkey,
            "generated_at": _utc_now_iso(),
            "data_source": {
                "aum_nav": {
                    "provider_order": source_order,
                    "providers": {
                        "yfinance": "yfinance.Ticker.info (totalAssets, navPrice)",
                        "alphavantage": "Alpha Vantage ETF_PROFILE (net_assets)",
                    },
                },
                "closes": "yfinance.download (Close)",
            },
            "calculation": {
                "primary_return_basis": (config.get("calc") or {}).get("primary_return_basis", "nav"),
                "secondary_close_series": bool(
                    (config.get("calc") or {}).get("compute_secondary_close_based_series", True)
                ),
            },
        },
        "data": {},
    }
    prev_doc = read_monthly_json(prev_path)

    # Refresh docs + metadata even when upserting into an existing month file.
    cur_doc["_README"] = build_readme_block()
    cur_doc.setdefault("metadata", {})["month"] = mkey
    cur_doc["metadata"]["data_source"] = {
        "aum_nav": {
            "provider_order": source_order,
            "providers": {
                "yfinance": "yfinance.Ticker.info (totalAssets, navPrice)",
                "alphavantage": "Alpha Vantage ETF_PROFILE (net_assets)",
            },
        },
        "closes": "yfinance.download (Close)",
    }
    cur_doc["metadata"]["calculation"] = {
        "primary_return_basis": (config.get("calc") or {}).get("primary_return_basis", "nav"),
        "secondary_close_series": bool((config.get("calc") or {}).get("compute_secondary_close_based_series", True)),
    }

    cur_doc.setdefault("metadata", {})["generated_at"] = _utc_now_iso()
    cur_doc["metadata"]["tickers_total"] = len(tickers)
    cur_doc["metadata"]["aum_nav_calls"] = {"alphavantage": 0}
    cur_doc["metadata"]["aum_nav_call_caps"] = {"alphavantage": int(alpha_cfg.get("max_calls_per_run", 25))}

    # Process each ticker
    all_points_for_agg: List[dict] = []

    for row in universe_rows:
        t = row.ticker

        aum, nav, updated_at, aum_nav_source, provider_warnings = fetch_aum_nav_with_fallbacks(
            t,
            source_order=[str(x) for x in source_order],
            yfinance_sleep_seconds=yfinance_sleep_seconds,
            alpha_cfg=alpha_cfg,
            alpha_key=alpha_key,
            call_counts=call_counts,
            cap_applied=cap_applied,
        )

        close_map = closes_by_ticker.get(t, {})
        close_t = safe_float(close_map.get(session_date_str))

        # Find prior point
        prior = get_prev_point(cur_doc, prev_doc, t, session_date_str)
        aum_prev = safe_float((prior or {}).get("aum"))
        nav_prev = safe_float((prior or {}).get("nav"))
        close_prev = safe_float((prior or {}).get("close"))

        r_nav = (nav / nav_prev) if (nav is not None and nav_prev is not None and nav_prev != 0) else None
        r_close = (close_t / close_prev) if (close_t is not None and close_prev is not None and close_prev != 0) else None

        flow_nav = compute_flow(aum, aum_prev, r_nav)
        flow_close = compute_flow(aum, aum_prev, r_close)

        warnings: List[str] = []
        warnings.extend(provider_warnings)
        if aum is None or nav is None:
            warnings.append("missing_aum_or_nav")
        if close_t is None:
            warnings.append("missing_close")
        if prior is None:
            warnings.append("missing_prior_day")

        implied_shares = (aum / nav) if (aum is not None and nav is not None and nav != 0) else None

        point = {
            "date": session_date_str,
            "aum": aum,
            "nav": nav,
            "close": close_t,
            "aum_nav_updated_at": updated_at,
            "aum_nav_source": aum_nav_source,
            "return_factor_nav": r_nav,
            "return_factor_close": r_close,
            "flow_nav": flow_nav,
            "flow_close": flow_close,
            "flow_nav_pct_aum": (flow_nav / aum) if (flow_nav is not None and aum not in (None, 0)) else None,
            "flow_close_pct_aum": (flow_close / aum) if (flow_close is not None and aum not in (None, 0)) else None,
            "implied_shares": implied_shares,
            "asset_class": row.asset_class,
            "category": row.category,
            "subcategory": row.subcategory,
            "notes": row.notes,
            "warnings": warnings,
        }

        # Write into per-ticker daily list
        tnode = (cur_doc.get("data") or {}).get(t) or {
            "ticker": t,
            "asset_class": row.asset_class,
            "category": row.category,
            "subcategory": row.subcategory,
            "notes": row.notes,
            "daily": [],
        }

        tnode["daily"] = upsert_daily_point(tnode.get("daily") or [], point)
        cur_doc.setdefault("data", {})[t] = tnode

        all_points_for_agg.append(point)

    # Save per-ticker
    cur_doc.setdefault("metadata", {})["aum_nav_calls"] = {
        "alphavantage": call_counts.get("alphavantage", 0),
    }
    cur_doc["metadata"]["aum_nav_call_caps_applied"] = {
        "alphavantage": bool(cap_applied.get("alphavantage")),
    }
    write_monthly_json(cur_path, cur_doc, indent=indent)

    # Aggregates
    if aggregates_enabled:
        base_meta = {
            "month": mkey,
            "generated_at": _utc_now_iso(),
            "data_source": {
                "aum_nav": {
                    "provider_order": source_order,
                    "providers": {
                        "yfinance": "yfinance.Ticker.info (totalAssets, navPrice)",
                        "alphavantage": "Alpha Vantage ETF_PROFILE (net_assets)",
                    },
                },
                "closes": "yfinance.download (Close)",
            },
        }

        def write_agg(prefix: str, group_key: str) -> None:
            agg_path = out_dir / f"{prefix}_{mkey}.json"
            existing = read_monthly_json(agg_path) or {
                "_README": {
                    "title": f"ETF Fund Flows Aggregates ({group_key})",
                    "description": f"Daily aggregate AUM and derived flows grouped by {group_key}.",
                    "formula": "For each date and group: sum(AUM), sum(flow_nav), sum(flow_close).",
                },
                "metadata": {**base_meta, "group_by": group_key},
                "data": {"daily": []},
            }

            # Refresh metadata on existing aggregate files.
            existing["metadata"] = {**base_meta, "group_by": group_key}

            # Compute groups for this session date only
            groups = (aggregate_points(all_points_for_agg, group_key)["daily"][0]["groups"]
                      if all_points_for_agg else {})

            existing.setdefault("metadata", {})["generated_at"] = _utc_now_iso()
            existing["metadata"]["tickers_total"] = len(tickers)
            existing["data"]["daily"] = upsert_agg_daily(existing.get("data", {}).get("daily", []), session_date_str, groups)
            write_monthly_json(agg_path, existing, indent=indent)

        write_agg(
            aggregates_cfg.get("asset_class_prefix", "etf_fund_flows_agg_asset_class"),
            "asset_class",
        )
        write_agg(
            aggregates_cfg.get("category_prefix", "etf_fund_flows_agg_category"),
            "category",
        )
        write_agg(
            aggregates_cfg.get("subcategory_prefix", "etf_fund_flows_agg_subcategory"),
            "subcategory",
        )

    print(f"✓ ETF fund flows generated for {len(tickers)} tickers on {session_date_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
