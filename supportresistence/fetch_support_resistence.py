"""Support / Resistence Collector

Fetches daily bars from the Alpaca Market Data API and produces a JSON snapshot
for SPY/QQQ/IWM/DIA containing:
- Traditional pivot levels (P, R1, R2, S1, S2)
- Fibonacci pivot levels (FP, FR1, FR2, FS1, FS2)
- SMA20 / SMA50 / SMA200

Notes:
- Pivot levels are computed from the most recent completed daily bar (H/L/C).
- SMAs are computed from daily closes up through the same reference bar.

Env vars:
- ALPACA_API_KEY or APCA-API-KEY-ID
- ALPACA_API_SECRET or APCA-API-SECRET-KEY
- ALPACA_DATA_URL (optional)

Docs:
- https://docs.alpaca.markets/reference/stockbars
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

from utils import (
    alpaca_headers,
    compute_fibonacci_pivots,
    compute_traditional_pivots,
    get_alpaca_credentials,
    parse_rfc3339_to_datetime,
    round_price,
    simple_moving_average,
    utc_now_iso,
    write_json,
)


# =============================================================================
# CONFIGURATION LOADING (mirrors stockwhales/optionswhales pattern)
# =============================================================================


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yml in this directory."""
    config_path = Path(__file__).parent / "config.yml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# =============================================================================
# SIMPLE RATE LIMITER (mirrors stockwhales/optionswhales pattern)
# =============================================================================


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = 60.0 / float(self.max_per_minute)
        self._last_request_ts: Optional[float] = None

    def wait_if_needed(self) -> None:
        now = time.time()
        if self._last_request_ts is None:
            self._last_request_ts = now
            return

        elapsed = now - self._last_request_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        self._last_request_ts = time.time()


# =============================================================================
# ALPACA API CLIENT (mirrors stockwhales/optionswhales pattern)
# =============================================================================


class AlpacaBarsClient:
    """Client for Alpaca Market Data Bars API."""

    BASE_URL = "https://data.alpaca.markets"

    def __init__(self, api_key: str, api_secret: str, rate_limiter: RateLimiter, timeout_seconds: int) -> None:
        self.rate_limiter = rate_limiter
        self.timeout_seconds = int(timeout_seconds)
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "accept": "application/json",
        }

    def _request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.rate_limiter.wait_if_needed()
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout_seconds)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                print("Rate limited, waiting 5s...")
                time.sleep(5)
                return self._request(endpoint, params)

            print(f"API error {response.status_code}: {response.text[:200]}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return None


def build_readme_section() -> Dict[str, Any]:
    return {
        "title": "Support / Resistence (Pivots + SMAs)",
        "description": "Daily support/resistance levels and moving averages for major index ETFs.",
        "purpose": (
            "Standardizes pivot-based support/resistance levels and long/medium/short trend reference "
            "levels (SMAs) for use in daily market commentary and dashboards."
        ),
        "metrics_explained": {
            "traditional_pivots": {
                "description": "Floor-trader (traditional) pivot levels derived from the prior session's High/Low/Close.",
                "formula": (
                    "P = (H + L + C)/3; R1 = 2P - L; S1 = 2P - H; R2 = P + (H - L); S2 = P - (H - L)"
                ),
                "interpretation": (
                    "Commonly used as potential intraday support/resistance zones. A sustained move above R1 can "
                    "suggest bullish momentum; below S1 can suggest bearish momentum."
                ),
            },
            "fibonacci_pivots": {
                "description": "Fibonacci pivot levels derived from the prior session's range (H-L) around the pivot point.",
                "formula": (
                    "FP = (H + L + C)/3; FR1 = FP + 0.382*(H-L); FR2 = FP + 0.618*(H-L); "
                    "FS1 = FP - 0.382*(H-L); FS2 = FP - 0.618*(H-L)"
                ),
                "interpretation": (
                    "Alternative support/resistance levels that scale by Fibonacci ratios. Often used when traders "
                    "prefer fib-derived zones over equal-range levels."
                ),
            },
            "sma20": {
                "description": "20-day simple moving average of daily closes.",
                "formula": "SMA20 = average(last 20 closes)",
                "interpretation": "Short-term trend proxy. Price above often signals near-term strength.",
            },
            "sma50": {
                "description": "50-day simple moving average of daily closes.",
                "formula": "SMA50 = average(last 50 closes)",
                "interpretation": "Medium-term trend proxy; commonly watched for pullbacks and trend health.",
            },
            "sma200": {
                "description": "200-day simple moving average of daily closes.",
                "formula": "SMA200 = average(last 200 closes)",
                "interpretation": "Long-term trend proxy; widely used as a bull/bear regime reference.",
            },
        },
        "trading_applications": {
            "support_resistance": (
                "Use pivot levels as reference zones for potential reactions; combine with trend (SMAs) "
                "and volatility context rather than treating any single level as a guarantee."
            )
        },
        "notes": {
            "reference_bar": "All calculations are based on the most recent completed 1Day bar returned by Alpaca.",
            "rounding": "All price levels are rounded for display; raw computations use full precision.",
            "naming": "Traditional pivots are P/R*/S*. Fibonacci pivots are FP/FR*/FS*.",
        },
    }


def fetch_daily_bars(
    client: AlpacaBarsClient,
    *,
    symbols: List[str],
    timeframe: str,
    start: str,
    end: str,
    feed: str,
    adjustment: str,
    limit: int,
) -> Dict[str, List[Dict[str, Any]]]:
    all_bars: Dict[str, List[Dict[str, Any]]] = {s: [] for s in symbols}
    page_token: Optional[str] = None

    # Alpaca's bars endpoint paginates across ALL symbols; results are ordered by symbol then time.
    while True:
        params: Dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "feed": feed,
            "adjustment": adjustment,
            "limit": limit,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token

        payload = client._request("/v2/stocks/bars", params)
        if not payload:
            break

        bars_by_symbol = payload.get("bars") or {}
        for symbol, bars in bars_by_symbol.items():
            if symbol in all_bars and isinstance(bars, list):
                all_bars[symbol].extend(bars)

        page_token = payload.get("next_page_token")
        if not page_token:
            break

    # Ensure chronological order per symbol
    for sym in all_bars:
        all_bars[sym].sort(key=lambda b: b.get("t") or "")

    return all_bars


def _bar_hlc(bar: Dict[str, Any]) -> Optional[Dict[str, float]]:
    try:
        return {
            "high": float(bar["h"]),
            "low": float(bar["l"]),
            "close": float(bar["c"]),
        }
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate pivot points + SMAs via Alpaca daily bars")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    parser.add_argument("--output", default=None, help="Override output filename")
    args = parser.parse_args()

    # Mirror existing collectors: config is loaded from local config.yml.
    # CLI flag is accepted for parity with earlier version but currently ignored.
    cfg = load_config()

    api_cfg = cfg.get("api", {})
    collector_cfg = cfg.get("collector", {})

    feed = str(api_cfg.get("feed") or "iex")
    adjustment = str(api_cfg.get("adjustment") or "all")
    timeout_seconds = int(api_cfg.get("timeout_seconds") or 30)
    rate_limit_per_minute = int(api_cfg.get("rate_limit_per_minute") or 180)

    tickers = list(collector_cfg.get("tickers") or ["SPY", "QQQ", "IWM", "DIA"])
    timeframe = str(collector_cfg.get("timeframe") or "1Day")
    lookback_days = int(collector_cfg.get("lookback_days") or 420)
    max_bars_limit = int(collector_cfg.get("max_bars_limit") or 1000)
    round_to_decimals = int(collector_cfg.get("round_to_decimals") or 2)

    output_filename = str(args.output or collector_cfg.get("output_filename") or "support_resistence.json")
    output_path = Path(output_filename)
    if not output_path.is_absolute():
        output_path = Path(__file__).parent / output_path

    api_key, api_secret = get_alpaca_credentials()
    headers = alpaca_headers(api_key, api_secret)

    # Use a date-only interval for daily bars. End is inclusive in the API.
    now_utc = datetime.now(timezone.utc)
    start_dt = (now_utc - timedelta(days=lookback_days)).date().isoformat()
    end_dt = now_utc.date().isoformat()

    rate_limiter = RateLimiter(rate_limit_per_minute)
    client = AlpacaBarsClient(api_key, api_secret, rate_limiter, timeout_seconds)

    # Note: headers kept for parity with previous version; client uses same auth internally.
    _ = headers

    bars = fetch_daily_bars(
        client,
        symbols=tickers,
        timeframe=timeframe,
        start=start_dt,
        end=end_dt,
        feed=feed,
        adjustment=adjustment,
        limit=max_bars_limit,
    )

    data: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for ticker in tickers:
        ticker_bars = bars.get(ticker) or []
        if not ticker_bars:
            errors[ticker] = "No bars returned"
            continue

        # Use the most recent *completed* daily bar.
        # If today's daily bar exists (often in-progress during market hours), use yesterday's bar instead.
        ref_index = -1
        if len(ticker_bars) >= 2 and isinstance(ticker_bars[-1].get("t"), str):
            try:
                last_dt = parse_rfc3339_to_datetime(ticker_bars[-1]["t"]).astimezone(timezone.utc)
                if last_dt.date() == datetime.now(timezone.utc).date():
                    ref_index = -2
            except Exception:
                pass

        ref_bar = ticker_bars[ref_index]
        hlc = _bar_hlc(ref_bar)
        if hlc is None:
            errors[ticker] = "Invalid bar shape (missing h/l/c)"
            continue

        ref_ts = ref_bar.get("t")
        ref_dt_iso = None
        ref_date = None
        if isinstance(ref_ts, str):
            try:
                dt = parse_rfc3339_to_datetime(ref_ts).astimezone(timezone.utc)
                ref_dt_iso = dt.isoformat()
                ref_date = dt.date().isoformat()
            except Exception:
                ref_dt_iso = ref_ts

        closes: List[float] = []
        bars_for_sma = ticker_bars[: ref_index + 1] if ref_index != -1 else ticker_bars
        for b in bars_for_sma:
            c = b.get("c")
            if c is None:
                continue
            try:
                closes.append(float(c))
            except Exception:
                continue

        sma20 = simple_moving_average(closes, 20)
        sma50 = simple_moving_average(closes, 50)
        sma200 = simple_moving_average(closes, 200)

        trad = compute_traditional_pivots(hlc["high"], hlc["low"], hlc["close"])
        fib = compute_fibonacci_pivots(hlc["high"], hlc["low"], hlc["close"])

        data[ticker] = {
            "reference_bar": {
                "timeframe": timeframe,
                "t": ref_dt_iso,
                "date": ref_date,
                "h": round_price(hlc["high"], round_to_decimals),
                "l": round_price(hlc["low"], round_to_decimals),
                "c": round_price(hlc["close"], round_to_decimals),
            },
            "traditional_pivots": {k: round_price(v, round_to_decimals) for k, v in trad.items()},
            "fibonacci_pivots": {k: round_price(v, round_to_decimals) for k, v in fib.items()},
            "sma": {
                "SMA20": round_price(sma20, round_to_decimals),
                "SMA50": round_price(sma50, round_to_decimals),
                "SMA200": round_price(sma200, round_to_decimals),
            },
            "inputs": {
                "bars_used": len(ticker_bars),
                "closes_used": len(closes),
                "feed": feed,
                "adjustment": adjustment,
            },
        }

    payload: Dict[str, Any] = {
        "_README": build_readme_section(),
        "metadata": {
            "generated_at": utc_now_iso(),
            "data_source": "Alpaca Market Data API",
            "endpoint": "/v2/stocks/bars",
            "feed": feed,
            "adjustment": adjustment,
            "timeframe": timeframe,
            "tickers": tickers,
            "tickers_count": len(tickers),
            "symbols_with_data": len(data),
            "lookback_days": lookback_days,
            "errors": errors,
        },
        "data": data,
    }

    write_json(str(output_path), payload)
    print(f"Wrote {output_path}")

    if errors:
        print("Warnings:")
        for k, v in errors.items():
            print(f"- {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
