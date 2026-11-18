"""Chunked S&P 500 download in advancedecline/fetch_volume_metrics_historical.py.

Yahoo rate-limits large batches, so the uncached path downloads in paced,
retry-wrapped chunks. Only the download/sleep boundary is faked.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

_TARGET = Path(__file__).resolve().parent.parent / "advancedecline" / "fetch_volume_metrics_historical.py"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("volume_metrics_under_test", _TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _download(calls):
    def download(tickers, **kwargs):
        calls.append((list(tickers), kwargs))
        return pd.DataFrame({t: [1.0] for t in tickers})
    return download


@pytest.mark.parametrize("n_tickers", [3, 10, 11, 25])
def test_every_ticker_downloaded_once_in_paced_retried_chunks(module, monkeypatch, n_tickers):
    calls, sleeps, retried = [], [], []

    def tracking_retry(fn, *args, **kwargs):
        retried.append(True)
        return fn(*args, **kwargs)

    monkeypatch.setattr(module, "with_429_retry", tracking_retry)
    tickers = [f"T{i}" for i in range(n_tickers)]

    result = module._download_chunked(
        tickers, period="6mo", chunk_size=10, sleep_seconds=7,
        download_fn=_download(calls), sleep_fn=sleeps.append,
    )

    chunks = [tickers_ for tickers_, _ in calls]
    assert [t for chunk in chunks for t in chunk] == tickers
    assert all(len(chunk) <= 10 for chunk in chunks)
    assert len(chunks) == math.ceil(n_tickers / 10)
    assert all(kwargs["period"] == "6mo" for _, kwargs in calls)
    assert sleeps == [7] * (len(chunks) - 1)  # between chunks, never after the last
    assert len(retried) == len(chunks)
    assert list(result.columns) == tickers


def test_cache_dir_uses_shared_breadth_cache_instead_of_downloading(module, monkeypatch, tmp_path):
    cached = pd.DataFrame({"A": [1.0]})
    fetcher = Mock()
    fetcher.fetch_prices.return_value = cached
    monkeypatch.setattr(module, "CachedDataFetcher", Mock(return_value=fetcher))
    chunked = Mock()
    monkeypatch.setattr(module, "_download_chunked", chunked)

    assert module.download_market_data(["A"], period="1y", cache_dir=str(tmp_path)) is cached
    chunked.assert_not_called()
    # Same cache entry as fetch_daily_breadth, so one CI attempt downloads the S&P 500 once.
    assert fetcher.fetch_prices.call_args.kwargs["reuse_within_run"] is True
