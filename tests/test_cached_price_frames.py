"""The majorindexes and meanreversion scripts read their prices from the price cache.

yfinance 1.x returns yf.download columns as a (Price, Ticker) MultiIndex. These
scripts used to test `symbol in df.columns` (always False for that layout), so
every symbol was downloaded twice: once through CachedDataFetcher, then again
with yf.Ticker(...).history. They also shared one cache key across different
ticker sets. Only the network boundary is faked here: CachedDataFetcher.fetch_prices
returns a canned frame and yf.Ticker records direct downloads.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import shared.cache_manager as cache_manager
import shared.yf_retry as retry_module
from shared.yf_frames import ticker_frame

REPO = Path(__file__).resolve().parent.parent

# Every script whose fetch_index_data has a CachedDataFetcher path.
CACHED_SCRIPTS = [
    "majorindexes/fetch_bonds.py",
    "majorindexes/fetch_commodities.py",
    "majorindexes/fetch_international.py",
    "majorindexes/fetch_currency.py",
    "majorindexes/fetch_dow_family.py",
    "majorindexes/fetch_emerging.py",
    "majorindexes/fetch_equal_weight.py",
    "majorindexes/fetch_growth_value.py",
    "majorindexes/fetch_sectors.py",
    "meanreversion/fetch_price_vs_ma.py",
    "meanreversion/fetch_ma_spreads.py",
]

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _exec(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ohlcv(closes, index=None) -> pd.DataFrame:
    closes = pd.Series(np.asarray(closes, dtype=float))
    if index is None:
        index = pd.bdate_range(end="2026-11-17", periods=len(closes))
    frame = pd.DataFrame(
        {"Open": closes.values, "High": closes.values + 1, "Low": closes.values - 1,
         "Close": closes.values, "Volume": 1000.0},
        index=index,
    )
    return frame


def price_ticker(frames: dict) -> pd.DataFrame:
    """yf.download(list) in yfinance 1.x: (Price, Ticker) columns, union of dates."""
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, axis=1).swaplevel(0, 1, axis=1).sort_index(axis=1, level=0, sort_remaining=False)
    df.columns.names = ["Price", "Ticker"]
    return df


def walk(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * (seed + 1) * np.exp(np.cumsum(rng.normal(0, 0.01, n)))


class Yahoo:
    """Records direct yf.Ticker downloads; serves the cache's frame from fetch_prices."""

    def __init__(self):
        self.frame = None          # DataFrame, or callable(tickers) -> DataFrame
        self.fetch_calls = []      # CachedDataFetcher.fetch_prices calls
        self.history_calls = []    # (symbol, period)
        self.info_calls = []
        self.direct = {}           # symbol -> frame served by Ticker.history
        self.fail_direct = False

    def fetch_prices(self, fetcher, tickers, start_date=None, end_date=None, cache_name="prices",
                     period=None, force_refresh=False, reuse_within_run=False):
        self.fetch_calls.append({"tickers": list(tickers), "cache_name": cache_name, "period": period})
        return self.frame(tickers) if callable(self.frame) else self.frame

    def ticker(self, symbol, session=None):
        yahoo = self

        class _Ticker:
            def history(self, period="1mo", **_kw):
                yahoo.history_calls.append((symbol, period))
                if yahoo.fail_direct:
                    return pd.DataFrame()
                frame = yahoo.direct.get(symbol, ohlcv(walk(300, 99)))
                frame = frame.copy()
                frame.index = frame.index.tz_localize("America/New_York")
                return frame

            @property
            def info(self):
                yahoo.info_calls.append(symbol)
                if yahoo.fail_direct:
                    raise RuntimeError("offline")
                return {"regularMarketPrice": 101.0, "regularMarketPreviousClose": 100.0,
                        "regularMarketChange": 1.0, "regularMarketChangePercent": 1.0}

        return _Ticker()


@pytest.fixture
def yahoo(monkeypatch):
    fake = Yahoo()
    monkeypatch.setattr(cache_manager.CachedDataFetcher, "fetch_prices",
                        lambda self, *a, **k: fake.fetch_prices(self, *a, **k))
    monkeypatch.setattr(retry_module.time, "sleep", lambda _s: None)
    return fake


@pytest.fixture
def load(monkeypatch, tmp_path, yahoo):
    def _load(rel: str):
        package = REPO / rel.split("/")[0]
        monkeypatch.setitem(sys.modules, "utils", _exec(f"utils_{package.name}", package / "utils.py"))
        module = _exec(f"{Path(rel).stem}_cached_under_test", REPO / rel)
        monkeypatch.setattr(module.yf, "Ticker", yahoo.ticker)
        monkeypatch.setattr(module.yf, "download", _no_direct_batch)
        if getattr(module, "time", None) is time:  # stub per-symbol pacing sleeps
            monkeypatch.setattr(module, "time", argparse.Namespace(sleep=lambda _s: None))
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        monkeypatch.setattr(module, "SCRIPT_DIR", out if isinstance(module.SCRIPT_DIR, Path) else str(out))
        module.args = argparse.Namespace(cache_dir=str(tmp_path / "cache"))
        monkeypatch.setattr(sys, "argv", ["prog", "--cache-dir", str(tmp_path / "cache")])
        return module

    return _load


def _no_direct_batch(*_a, **_k):
    raise AssertionError("unexpected direct yf.download")


def universe(module) -> list:
    if hasattr(module, "SECTORS"):
        return [s["symbol"] for s in module.SECTORS]
    if hasattr(module, "INTL_CONFIG"):
        return [i["symbol"] for region in module.INTL_CONFIG["regions"].values() for i in region]
    return [i["symbol"] for i in module.INDICES]


def rows_kept(module) -> int:
    return module.FETCH_DAYS if hasattr(module, "FETCH_DAYS") else module.HISTORICAL_DAYS


def fetch(module, symbol):
    period = "5y" if hasattr(module, "FETCH_DAYS") else "1y"
    return module.fetch_index_data(symbol, period=period, cache_dir=module.args.cache_dir)


def distinct_frames(symbols, n) -> dict:
    """Each symbol its own price level; the first one misses a date the others traded."""
    index = pd.bdate_range(end="2026-11-17", periods=n)
    frames = {s: ohlcv(walk(n, i), index) for i, s in enumerate(symbols)}
    frames[symbols[0]] = frames[symbols[0]].drop(index[n // 2])
    return frames


# --- ticker_frame ---------------------------------------------------------------

def test_ticker_frame_reads_every_yfinance_layout():
    a, b = ohlcv([1.0, 2.0, 3.0]), ohlcv([10.0, 20.0, 30.0])
    ticker_price = pd.concat({"A": a, "B": b}, axis=1)
    for layout in (price_ticker({"A": a, "B": b}), ticker_price):
        pd.testing.assert_frame_equal(ticker_frame(layout, "B")[list(b.columns)], b, check_names=False, check_freq=False)
        assert ticker_frame(layout, "C") is None
    assert ticker_frame(a, "A", single=True).equals(a)
    assert ticker_frame(a, "A") is None  # a flat frame names no ticker unless it was requested alone
    assert ticker_frame(None, "A") is None and ticker_frame(pd.DataFrame(), "A") is None


def test_ticker_frame_drops_dates_only_other_tickers_traded():
    index = pd.bdate_range("2026-01-05", periods=4)
    a = ohlcv([1.0, 2.0, 3.0], index[[0, 1, 3]])
    b = ohlcv([5.0, 6.0, 7.0, 8.0], index)
    out = ticker_frame(price_ticker({"A": a, "B": b}), "A")
    assert list(out.index) == list(a.index)
    assert list(out["Close"]) == [1.0, 2.0, 3.0]


def test_ticker_frame_rejects_symbol_with_no_close():
    a = ohlcv([1.0, 2.0])
    b = ohlcv([np.nan, np.nan])
    assert ticker_frame(price_ticker({"A": a, "B": b}), "B") is None


# --- scripts read the cached frame ------------------------------------------------

@pytest.mark.parametrize("rel", CACHED_SCRIPTS)
def test_cached_multiindex_frame_is_used_without_direct_download(load, yahoo, rel):
    module = load(rel)
    symbols = universe(module)
    n = rows_kept(module) + 40
    frames = {s: ohlcv(walk(n, i)) for i, s in enumerate(symbols)}
    yahoo.frame = price_ticker(frames)

    for symbol in symbols:
        df = fetch(module, symbol)
        assert list(df["Close"]) == list(frames[symbol]["Close"].tail(rows_kept(module)))

    assert yahoo.history_calls == []
    assert len(yahoo.fetch_calls) == 1  # one batched cache fetch serves every symbol


@pytest.mark.parametrize("rel", CACHED_SCRIPTS)
def test_symbol_missing_from_cached_frame_falls_back_to_direct_download(load, yahoo, rel):
    module = load(rel)
    symbols = universe(module)
    n = rows_kept(module) + 40
    yahoo.frame = price_ticker({s: ohlcv(walk(n, i)) for i, s in enumerate(symbols) if s != symbols[0]})
    yahoo.direct[symbols[0]] = ohlcv(walk(n, 7))

    df = fetch(module, symbols[0])
    for symbol in symbols[1:]:
        fetch(module, symbol)

    assert {s for s, _ in yahoo.history_calls} == {symbols[0]}
    assert list(df["Close"]) == list(yahoo.direct[symbols[0]]["Close"].tail(rows_kept(module)))


@pytest.mark.parametrize("rel", CACHED_SCRIPTS)
def test_symbol_whose_cached_rows_stop_early_falls_back(load, yahoo, rel):
    # A batch refresh that failed for one ticker leaves its recent rows empty;
    # its last cached bar must not be published as the current one.
    module = load(rel)
    symbols = universe(module)
    if len(symbols) < 2:
        pytest.skip("single-symbol universe")
    n = rows_kept(module) + 40
    frames = {s: ohlcv(walk(n, i)) for i, s in enumerate(symbols)}
    frames[symbols[0]] = frames[symbols[0]].iloc[:-3]
    yahoo.frame = price_ticker(frames)

    for symbol in symbols:
        fetch(module, symbol)

    assert {s for s, _ in yahoo.history_calls} == {symbols[0]}


@pytest.mark.parametrize("rel", CACHED_SCRIPTS)
def test_symbols_do_not_contaminate_each_other(load, yahoo, rel):
    module = load(rel)
    symbols = universe(module)
    n = rows_kept(module) + 40
    frames = distinct_frames(symbols, n)
    yahoo.frame = price_ticker(frames)

    for symbol in symbols:
        df = fetch(module, symbol)
        expected = frames[symbol].tail(rows_kept(module))
        assert list(df.index) == list(expected.index), symbol
        assert list(df["Close"]) == list(expected["Close"]), symbol
        assert df["Close"].notna().all()
    assert yahoo.history_calls == []


def test_cache_keys_never_shared_across_ticker_sets(load, yahoo):
    """Two requests under one cache key must ask for the same tickers and period:
    CachedDataFetcher merges new rows into whatever that key already holds."""
    keys = defaultdict(set)
    for rel in CACHED_SCRIPTS:
        module = load(rel)
        yahoo.fetch_calls.clear()
        yahoo.frame = pd.DataFrame()  # content is irrelevant here; direct fallback serves it
        for symbol in universe(module):
            fetch(module, symbol)
        for call in yahoo.fetch_calls:
            keys[call["cache_name"]].add((frozenset(call["tickers"]), call["period"]))
    shared = {k: v for k, v in keys.items() if len(v) > 1}
    assert not shared, shared


# --- outputs the website reads (bonds, commodities, mean reversion) --------------

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def run_main(load, yahoo, rel, rows):
    module = load(rel)
    symbols = universe(module)
    yahoo.frame = price_ticker({s: ohlcv(walk(rows, i)) for i, s in enumerate(symbols)})
    module.main()
    out = Path(module.SCRIPT_DIR)
    return module, symbols, {p.name: json.loads(p.read_text()) for p in out.glob("*.json")}


@pytest.mark.parametrize("rel,snapshot,historical,website_symbols", [
    ("majorindexes/fetch_bonds.py", "bond_treasury_indices.json", "bond_treasury_indices_historical.json",
     {"^TNX", "^TYX", "^FVX", "^IRX"}),  # MajorIndexesSnapshot.tsx, HomeMarketTerminal.tsx
    ("majorindexes/fetch_commodities.py", "commodity_indices.json", "commodity_indices_historical.json",
     {"GC=F", "SI=F", "CL=F", "NG=F"}),  # MajorIndexesSnapshot.tsx
])
def test_major_index_outputs_from_cache_keep_website_contract(load, yahoo, rel, snapshot, historical, website_symbols):
    module, symbols, files = run_main(load, yahoo, rel, 300)

    assert yahoo.history_calls == []
    assert len(yahoo.fetch_calls) == 1  # snapshot and historical share one cache fetch
    body = files[snapshot]
    assert set(body["indices"]) == set(symbols) >= website_symbols
    for row in body["indices"].values():
        assert finite(row["current_price"])
        assert finite(row["daily_change"]) and finite(row["daily_change_percent"])
        for key in ("52_week_high", "52_week_low", "1_month_percent", "6_month_percent"):
            assert finite(row[key]), key
        assert row["pivot_points"] and all(finite(v) for v in row["pivot_points"].values())
    history = files[historical]["indices"]
    assert set(history) == set(symbols)
    for row in history.values():
        assert len(row["data"]) == module.HISTORICAL_DAYS
        for point in row["data"]:
            assert DATE.match(point["date"])
            assert finite(point["close"]) and isinstance(point["volume"], int)


MA_KEYS = ("ma_20", "ma_50", "ma_200")
PAIRS = ("short_term_vs_intermediate", "short_term_vs_long_term", "intermediate_vs_long_term")


def test_price_vs_ma_outputs_from_cache_keep_website_contract(load, yahoo):
    # MeanReversionSummary.tsx, PriceVsMACharts.tsx, ZScoreCharts.tsx, DetailedMetrics.tsx
    module, symbols, files = run_main(load, yahoo, "meanreversion/fetch_price_vs_ma.py", 1100)
    assert yahoo.history_calls == [] and len(yahoo.fetch_calls) == 1
    snap = files["price_vs_ma_snapshot.json"]["indices"]
    assert set(snap) == set(symbols) >= {"SPY", "QQQ", "IWM"}
    for row in snap.values():
        assert DATE.match(row["date"]) and finite(row["current_price"])
        assert isinstance(row["trend_alignment"], str)
        for ma in MA_KEYS:
            assert finite(row["moving_averages"][ma])
            metrics = row["metrics_by_ma"][ma]
            assert all(finite(metrics[k]) for k in ("distance", "distance_percent", "zscore"))
            assert isinstance(metrics["signal"], str)
    hist = files["price_vs_ma_historical.json"]["indices"]
    for row in hist.values():
        assert len(row["data"]) == module.HISTORICAL_DAYS
        assert set(row["data_quality"]) == {"required_periods", "actual_periods", "completeness_percent", "sufficient_data"}
        for point in row["data"]:
            assert DATE.match(point["date"]) and finite(point["price"])
            for ma in MA_KEYS:
                assert finite(point["moving_averages"][ma])
                assert all(finite(point["metrics"][ma][k]) for k in ("distance", "distance_percent", "zscore"))


def test_ma_spreads_outputs_from_cache_keep_website_contract(load, yahoo):
    # MASpreadCharts.tsx, MeanReversionSummary.tsx, DetailedMetrics.tsx
    module, symbols, files = run_main(load, yahoo, "meanreversion/fetch_ma_spreads.py", 1100)
    assert yahoo.history_calls == [] and len(yahoo.fetch_calls) == 1
    snap = files["ma_spreads_snapshot.json"]["indices"]
    assert set(snap) == set(symbols) >= {"SPY", "QQQ", "IWM"}
    for row in snap.values():
        assert DATE.match(row["date"]) and finite(row["current_price"])
        assert all(finite(row["moving_averages"][ma]) for ma in MA_KEYS)
        for pair in PAIRS:
            metrics = row["ma_pairs"][pair]
            assert all(finite(metrics[k]) for k in ("spread", "spread_percent", "zscore"))
            assert isinstance(metrics["ma_short"], int) and isinstance(metrics["ma_long"], int)
            assert all(isinstance(metrics[k], str) for k in ("signal", "alignment", "alignment_note"))
    hist = files["ma_spreads_historical.json"]["indices"]
    for row in hist.values():
        assert len(row["data"]) == module.HISTORICAL_DAYS
        for point in row["data"]:
            assert DATE.match(point["date"]) and finite(point["price"])
            for pair in PAIRS:
                assert all(finite(point["ma_pairs"][pair][k]) for k in ("spread", "spread_percent", "zscore"))


# --- zero-success guard ------------------------------------------------------------

GUARDED = [
    ("meanreversion/fetch_ma_spreads.py", ["ma_spreads_snapshot.json", "ma_spreads_historical.json"]),
    ("meanreversion/fetch_price_vs_ma.py", ["price_vs_ma_snapshot.json", "price_vs_ma_historical.json"]),
    ("majorindexes/fetch_currency.py", ["currency_indices.json", "currency_indices_historical.json"]),
    ("majorindexes/fetch_dow_family.py", ["dow_family_indices.json", "dow_family_indices_historical.json"]),
    ("majorindexes/fetch_emerging.py", ["emerging_markets_indices.json", "emerging_markets_indices_historical.json"]),
    ("majorindexes/fetch_equal_weight.py", ["us_equal_weight_indices.json", "us_equal_weight_indices_historical.json"]),
]


@pytest.mark.parametrize("rel,outputs", GUARDED)
def test_all_symbols_failing_exits_nonzero_and_keeps_previous_files(load, yahoo, rel, outputs):
    module = load(rel)
    out = Path(module.SCRIPT_DIR)
    good = {name: f'{{"indices": {{"OLD": {{"current_price": {i + 1}.5}}}}}}\n'.encode() for i, name in enumerate(outputs)}
    for name, data in good.items():
        (out / name).write_bytes(data)
    yahoo.frame = pd.DataFrame()
    yahoo.fail_direct = True

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 1
    for name, data in good.items():
        assert (out / name).read_bytes() == data, name
