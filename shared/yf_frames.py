"""Per-ticker frames from yfinance downloads, and cached batches of them.

yfinance 1.x returns ``yf.download`` columns as a (Price, Ticker) MultiIndex
(even for one ticker), ``group_by="ticker"`` gives (Ticker, Price), and older
versions or ``Ticker.history`` give flat OHLCV columns. ``ticker_frame`` reads
one ticker out of any of these layouts.

``cached_ticker_frames`` fetches a script's whole symbol set through
``CachedDataFetcher`` in one call, under a cache key derived from the symbol
set and period, so scripts never merge one symbol's rows into another's cache.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd


def ticker_frame(df: Optional[pd.DataFrame], symbol: str, *, single: bool = False) -> Optional[pd.DataFrame]:
    """Return ``symbol``'s OHLCV columns from a yfinance frame, or None.

    Args:
        df: A yf.download or Ticker.history result.
        symbol: The ticker to extract.
        single: The frame was requested for ``symbol`` alone, so flat OHLCV
            columns belong to it.

    Rows where every field is NaN (dates on which only other tickers in a
    batch traded) are dropped. Returns None when the ticker is absent or has
    no usable Close.
    """
    if df is None or getattr(df, "empty", True):
        return None
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        level0 = set(cols.get_level_values(0))
        level1 = set(cols.get_level_values(1))
        if "Close" in level0 and symbol in level1:
            out = df.xs(symbol, axis=1, level=1)
        elif "Close" in level1 and symbol in level0:
            out = df.xs(symbol, axis=1, level=0)
        else:
            return None
    elif single and "Close" in cols:
        out = df
    else:
        return None
    out = out.dropna(how="all")
    if "Close" not in out.columns or out["Close"].dropna().empty:
        return None
    return out


def cache_key(prefix: str, symbols: Iterable[str], period: str) -> str:
    """Cache name unique to (symbol set, period): equal sets share it, different sets never do."""
    digest = hashlib.sha256(",".join(sorted(set(symbols))).encode()).hexdigest()[:10]
    return f"{prefix}_{period}_{digest}"


def cached_ticker_frames(
    symbols: Iterable[str],
    *,
    period: str,
    cache_dir: str,
    prefix: str,
    memo: Optional[dict] = None,
    reuse_within_run: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Fetch ``symbols`` through the price cache in one call and split them per ticker.

    A symbol is left out (so the caller downloads it directly) when the cached
    frame has no usable Close for it, or when its last Close is older than the
    frame's newest date: a batch download that failed for one ticker leaves
    that ticker's recent rows empty, and its last bar must not pass as current.

    ``memo`` (a dict the caller keeps for the process) returns the same split
    to the snapshot and historical builders without a second download.
    """
    from shared.cache_manager import CachedDataFetcher

    symbols = list(dict.fromkeys(symbols))
    name = cache_key(prefix, symbols, period)
    memo_key = (str(Path(cache_dir).resolve()), name)
    if memo is not None and memo_key in memo:
        return memo[memo_key]

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    fetcher = CachedDataFetcher(cache_dir=str(cache_dir))
    try:
        df = fetcher.fetch_prices(symbols, period=period, cache_name=name, reuse_within_run=reuse_within_run)
    except Exception as e:  # the caller's direct download is the fallback
        print(f"Cached fetch failed for {name}: {e}")
        df = None

    frames: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = ticker_frame(df, symbol, single=len(symbols) == 1)
        if frame is not None:
            frames[symbol] = frame
    if frames:
        newest = max(f["Close"].last_valid_index() for f in frames.values())
        frames = {s: f for s, f in frames.items() if f["Close"].last_valid_index() >= newest}

    if memo is not None:
        memo[memo_key] = frames
    return frames
