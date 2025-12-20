from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import yaml


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_env_template(value: Any) -> Any:
    """Resolves ${ENV:default} templates inside config.yml values."""
    if not isinstance(value, str):
        return value

    if not value.startswith("${") or not value.endswith("}"):
        return value

    inner = value[2:-1]
    if ":" in inner:
        env_name, default_value = inner.split(":", 1)
    else:
        env_name, default_value = inner, ""

    return os.getenv(env_name, default_value)


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return parse_env_template(obj)

    return _walk(raw)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
        f.write("\n")


def round_price(value: Optional[float], decimals: int) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def parse_rfc3339_to_datetime(value: str) -> datetime:
    # Alpaca timestamps are RFC-3339; commonly end with 'Z'
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def get_alpaca_credentials() -> Tuple[str, str]:
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA-API-KEY-ID")
    api_secret = os.getenv("ALPACA_API_SECRET") or os.getenv("APCA-API-SECRET-KEY")

    if not api_key or not api_secret:
        raise ValueError(
            "Missing Alpaca API credentials. Set ALPACA_API_KEY and ALPACA_API_SECRET (or APCA-API-KEY-ID / APCA-API-SECRET-KEY)."
        )

    return api_key, api_secret


def alpaca_headers(api_key: str, api_secret: str) -> Dict[str, str]:
    return {
        "accept": "application/json",
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }


def compute_traditional_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    p = (high + low + close) / 3.0
    r1 = (2.0 * p) - low
    s1 = (2.0 * p) - high
    r2 = p + (high - low)
    s2 = p - (high - low)
    return {"P": p, "R1": r1, "R2": r2, "S1": s1, "S2": s2}


def compute_fibonacci_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    p = (high + low + close) / 3.0
    rng = high - low
    r1 = p + 0.382 * rng
    r2 = p + 0.618 * rng
    s1 = p - 0.382 * rng
    s2 = p - 0.618 * rng
    return {"FP": p, "FR1": r1, "FR2": r2, "FS1": s1, "FS2": s2}


def simple_moving_average(values: Iterable[float], window: int) -> Optional[float]:
    vals = list(values)
    if window <= 0:
        return None
    if len(vals) < window:
        return None
    return sum(vals[-window:]) / float(window)
