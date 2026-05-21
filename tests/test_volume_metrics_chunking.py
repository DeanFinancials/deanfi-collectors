"""Tests for chunked download logic in fetch_volume_metrics_historical.py.

Strategy: extract and test the _download_chunked helper in isolation by
injecting fake download_fn and sleep_fn dependencies. All heavy deps
(pandas, yfinance, yaml, shared.*) are stubbed via sys.modules injection
so we never hit the network.

The _download_chunked helper accepts injected download_fn and sleep_fn, so
tests verify call-counts and argument shapes without any real I/O.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parent.parent
_TARGET = _REPO / "advancedecline" / "fetch_volume_metrics_historical.py"


# ---------------------------------------------------------------------------
# Fake "DataFrame" — just a sentinel so concat and return values are truthy
# ---------------------------------------------------------------------------


class FakeDF:
    """Minimal stand-in for pd.DataFrame; only needs to support concat."""

    def __init__(self, name="df"):
        self.name = name


def _fake_concat(dfs, axis=1):
    result = FakeDF("concat_result")
    result.sources = list(dfs)
    return result


# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------


def _make_fake_pandas():
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = FakeDF
    fake_pd.concat = _fake_concat
    return fake_pd


def _make_fake_yaml():
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda f: {
        "download_period": "1y",
        "output_files": {"volume_metrics_historical": "volume_metrics_historical.json"},
    }
    return fake_yaml


def _make_fake_cache_manager():
    mod = types.ModuleType("shared.cache_manager")

    class FakeCachedDataFetcher:
        def __init__(self, *, cache_dir):
            self.cache_dir = cache_dir

        def fetch_prices(self, *, tickers, period, cache_name):
            result = FakeDF("cached")
            result.from_cache = True
            return result

    mod.CachedDataFetcher = FakeCachedDataFetcher
    return mod


def _make_fake_spx_universe():
    mod = types.ModuleType("shared.spx_universe")
    mod.fetch_spx_tickers = lambda: [f"T{i}" for i in range(503)]
    return mod


def _make_fake_yfinance():
    fake_yf = types.ModuleType("yfinance")
    fake_yf.download = MagicMock(name="yf.download", return_value=FakeDF("raw"))
    return fake_yf


def _make_fake_yf_retry():
    mod = types.ModuleType("shared.yf_retry")

    def passthrough_retry(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    mod.with_429_retry = passthrough_retry
    return mod


def _load_target():
    """
    Load fetch_volume_metrics_historical with all heavy deps stubbed.
    Returns (module, fake_yfinance_mod, fake_yf_retry_mod).
    """
    # Inject stubs into sys.modules BEFORE loading the module
    fake_pd = _make_fake_pandas()
    sys.modules["pandas"] = fake_pd

    fake_yaml = _make_fake_yaml()
    sys.modules["yaml"] = fake_yaml

    fake_cm = _make_fake_cache_manager()
    sys.modules["shared.cache_manager"] = fake_cm

    fake_spx = _make_fake_spx_universe()
    sys.modules["shared.spx_universe"] = fake_spx

    fake_yf = _make_fake_yfinance()
    sys.modules["yfinance"] = fake_yf

    fake_yf_retry = _make_fake_yf_retry()
    sys.modules["shared.yf_retry"] = fake_yf_retry

    spec = importlib.util.spec_from_file_location(
        "fetch_volume_metrics_historical", _TARGET
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_volume_metrics_historical"] = mod
    spec.loader.exec_module(mod)
    return mod, fake_yf, fake_yf_retry


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mod_and_fakes():
    sys.modules.pop("fetch_volume_metrics_historical", None)
    return _load_target()


# ---------------------------------------------------------------------------
# Tests for _download_chunked
# ---------------------------------------------------------------------------


class TestDownloadChunked:

    @pytest.mark.parametrize("n_tickers, expected_chunks", [
        (50, 1),   # well below chunk boundary
        (100, 1),  # exactly at chunk boundary — still one chunk
        (101, 2),  # one over boundary — splits into two
        (500, 5),  # exact multiple
        (503, 6),  # realistic S&P 500 universe size
    ])
    def test_chunk_count_and_sleep_count(self, mod_and_fakes, n_tickers, expected_chunks):
        """download_fn is called once per chunk; sleep_fn is called between chunks only."""
        mod, _, _ = mod_and_fakes
        download_calls = []
        sleep_calls = []

        def fake_download(tickers, **kwargs):
            download_calls.append(list(tickers))
            return FakeDF()

        tickers = [f"T{i}" for i in range(n_tickers)]
        mod._download_chunked(
            tickers, period="1y",
            download_fn=fake_download,
            sleep_fn=lambda s: sleep_calls.append(s),
        )

        assert len(download_calls) == expected_chunks
        assert len(sleep_calls) == expected_chunks - 1

    def test_all_tickers_present_in_download_calls(self, mod_and_fakes):
        """Every ticker appears in exactly one chunk's download call."""
        mod, _, _ = mod_and_fakes
        seen_tickers = []

        def fake_download(tickers, **kwargs):
            seen_tickers.extend(list(tickers))
            return FakeDF()

        tickers = [f"T{i}" for i in range(250)]
        mod._download_chunked(
            tickers, period="1y",
            download_fn=fake_download,
            sleep_fn=lambda s: None,
        )

        assert sorted(seen_tickers) == sorted(tickers)

    def test_sleep_not_after_last_chunk(self, mod_and_fakes):
        """Sleep must NOT be called after the final chunk."""
        mod, _, _ = mod_and_fakes
        download_count = []
        sleep_count = []

        def fake_download(tickers, **kwargs):
            download_count.append(1)
            return FakeDF()

        def fake_sleep(s):
            sleep_count.append(1)

        tickers = [f"T{i}" for i in range(200)]
        mod._download_chunked(
            tickers, period="1y",
            download_fn=fake_download,
            sleep_fn=fake_sleep,
        )

        assert len(download_count) == 2
        assert len(sleep_count) == 1  # between chunk 1 and 2 only

    def test_no_sleep_for_single_chunk(self, mod_and_fakes):
        mod, _, _ = mod_and_fakes
        sleep_calls = []

        tickers = ["AAPL", "MSFT", "GOOG"]
        mod._download_chunked(
            tickers, period="1y",
            download_fn=lambda t, **kw: FakeDF(),
            sleep_fn=lambda s: sleep_calls.append(s),
        )

        assert sleep_calls == []

    def test_period_forwarded_to_download_fn(self, mod_and_fakes):
        """period kwarg is forwarded to the download_fn."""
        mod, _, _ = mod_and_fakes
        captured = {}

        def fake_download(tickers, **kwargs):
            captured.update(kwargs)
            return FakeDF()

        mod._download_chunked(
            ["A", "B"], period="6mo",
            download_fn=fake_download,
            sleep_fn=lambda s: None,
        )

        assert captured.get("period") == "6mo"

    def test_chunk_size_is_at_most_100(self, mod_and_fakes):
        """No single download call should receive more than 100 tickers."""
        mod, _, _ = mod_and_fakes
        chunk_sizes = []

        def fake_download(tickers, **kwargs):
            chunk_sizes.append(len(list(tickers)))
            return FakeDF()

        tickers = [f"T{i}" for i in range(503)]
        mod._download_chunked(
            tickers, period="1y",
            download_fn=fake_download,
            sleep_fn=lambda s: None,
        )

        assert all(s <= 100 for s in chunk_sizes), f"Chunk too large: {max(chunk_sizes)}"


# ---------------------------------------------------------------------------
# Tests for download_market_data() integration
# ---------------------------------------------------------------------------


class TestDownloadMarketDataIntegration:

    def test_uncached_path_calls_download_chunked(self, mod_and_fakes, monkeypatch):
        mod, _, _ = mod_and_fakes
        chunked_calls = []
        captured_period = []

        def fake_chunked(tickers, *, period, **kwargs):
            chunked_calls.append(list(tickers))
            captured_period.append(period)
            return FakeDF()

        monkeypatch.setattr(mod, "_download_chunked", fake_chunked)

        tickers = [f"T{i}" for i in range(503)]
        mod.download_market_data(tickers, period="1y", cache_dir=None)

        assert len(chunked_calls) == 1
        assert chunked_calls[0] == tickers
        assert captured_period[0] == "1y"

    def test_cached_path_does_not_call_download_chunked(self, mod_and_fakes, monkeypatch, tmp_path):
        mod, _, _ = mod_and_fakes
        chunked_calls = []

        def fake_chunked(*args, **kwargs):
            chunked_calls.append(True)

        monkeypatch.setattr(mod, "_download_chunked", fake_chunked)

        # cache_dir non-None → uses CachedDataFetcher, not chunked
        mod.download_market_data(["AAPL"], period="1y", cache_dir=str(tmp_path))

        assert chunked_calls == []

    def test_cached_path_returns_result(self, mod_and_fakes, tmp_path):
        mod, _, _ = mod_and_fakes
        result = mod.download_market_data(["AAPL"], period="1y", cache_dir=str(tmp_path))
        # FakeCachedDataFetcher marks its result with from_cache=True
        assert getattr(result, "from_cache", False) is True


# ---------------------------------------------------------------------------
# Tests verifying with_429_retry is used per chunk
# ---------------------------------------------------------------------------


class TestWith429RetryPerChunk:

    @pytest.mark.parametrize("n_tickers", [250, 503])
    def test_retry_called_once_per_chunk(self, mod_and_fakes, monkeypatch, n_tickers):
        """_download_chunked wraps each chunk's download_fn call with with_429_retry."""
        mod, _, _ = mod_and_fakes
        retry_calls = []

        def tracking_retry(fn, *args, **kwargs):
            retry_calls.append(True)
            return fn(*args, **kwargs)

        monkeypatch.setattr(mod, "with_429_retry", tracking_retry, raising=False)

        tickers = [f"T{i}" for i in range(n_tickers)]
        mod._download_chunked(
            tickers,
            period="1y",
            download_fn=lambda t, **kw: FakeDF(),
            sleep_fn=lambda s: None,
        )

        assert len(retry_calls) == math.ceil(n_tickers / 100)
