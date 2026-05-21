"""Tests for batched yf.download in majorindexes/fetch_us_major.py.

Verifies that the 6 core US indices are fetched in a single yf.download call,
wrapped in with_429_retry, and that per-ticker DataFrames are extracted from
the MultiIndex column response.

All heavy deps (pandas, yfinance, yaml, shared.*, utils) are stubbed via
sys.modules injection so tests never touch the network or disk.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parent.parent
_TARGET = _REPO / "majorindexes" / "fetch_us_major.py"


# ---------------------------------------------------------------------------
# Fake pandas — minimal MultiIndex / DataFrame stand-ins
# ---------------------------------------------------------------------------


class FakeMultiIndex:
    """Stand-in for pd.MultiIndex with the operations we need."""

    def __init__(self, level0_values):
        self._level0 = list(level0_values)

    def get_level_values(self, level: int):
        if level == 0:
            return self._level0
        raise ValueError(f"FakeMultiIndex only supports level 0; got {level}")


class FakeIndex:
    """Flat (non-MultiIndex) column stand-in."""

    def __init__(self, values):
        self._values = list(values)


class FakePerTickerDF:
    """A small per-ticker DataFrame produced by df[symbol]."""

    def __init__(self, symbol: str, rows: int = 252):
        self.symbol = symbol
        self._rows = rows
        # Mark as a true (non-empty) DataFrame
        self.empty = rows == 0

    def __len__(self):
        return self._rows


class FakeSeries:
    """Tiny Series stand-in for sector processing tests."""

    def __init__(self, values=None):
        self._values = list(values or [100, 101])

    def mean(self):
        return sum(self._values) / len(self._values)


class FakeILoc:
    """Supports df.iloc[-2] for pivot-point calculations."""

    def __getitem__(self, index):
        return {"High": 102, "Low": 99, "Close": 101}


class FakeProcessableTickerDF(FakePerTickerDF):
    """Per-ticker frame with just enough surface area for fetch_sectors output paths."""

    columns = ["Open", "High", "Low", "Close", "Volume"]

    def __init__(self, symbol: str, rows: int = 252):
        super().__init__(symbol, rows=rows)
        self.iloc = FakeILoc()

    def __getitem__(self, key):
        if key in self.columns:
            return FakeSeries()
        raise KeyError(key)

    def tail(self, rows):
        return self


class FakeTickerDFWithTrailingEmptyClose(FakeProcessableTickerDF):
    """Frame where yfinance returned a trailing row with no Close value."""

    def __init__(self, symbol: str, rows: int = 252):
        super().__init__(symbol, rows=rows)
        self.cleaned = False

    def dropna(self, *, subset=None, **kwargs):
        if subset == ["Close"]:
            cleaned = FakeTickerDFWithTrailingEmptyClose(self.symbol, rows=self._rows - 1)
            cleaned.cleaned = True
            return cleaned
        return self


class FakeBatchDF:
    """Stand-in for the MultiIndex DataFrame returned by yf.download(group_by='ticker')."""

    def __init__(self, symbol_to_df: dict, *, multiindex: bool = True):
        self._symbol_to_df = symbol_to_df
        if multiindex:
            self.columns = FakeMultiIndex(list(symbol_to_df.keys()))
        else:
            self.columns = FakeIndex(["Open", "High", "Low", "Close", "Volume"])
        self.empty = len(symbol_to_df) == 0

    def __getitem__(self, key):
        if key not in self._symbol_to_df:
            raise KeyError(key)
        return self._symbol_to_df[key]


# ---------------------------------------------------------------------------
# Module-loading helpers
# ---------------------------------------------------------------------------


def _make_fake_pandas():
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = FakePerTickerDF
    fake_pd.MultiIndex = FakeMultiIndex
    fake_pd.Timestamp = lambda x=None: x
    fake_pd.isna = lambda x: x is None
    fake_pd.concat = lambda dfs, **kw: dfs
    return fake_pd


def _make_fake_yaml():
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda f: {
        "us_major_etf_prices": {
            "output_file": "us_major_etf_prices.json",
            "tickers": ["SPY", "DIA", "IWM", "QQQ"],
            "update_frequency": "Every 10 minutes during market hours",
        },
        "us_major_indices": {
            "output_files": {
                "snapshot": "us_major_indices.json",
                "historical": "us_major_indices_historical.json",
            },
            "indices": [
                {"symbol": "^GSPC", "name": "S&P 500", "description": "Large-cap"},
                {"symbol": "^DJI", "name": "Dow Jones", "description": "Blue-chip"},
                {"symbol": "^IXIC", "name": "Nasdaq Composite", "description": "Tech-heavy"},
                {"symbol": "^NDX", "name": "Nasdaq-100", "description": "Top 100"},
                {"symbol": "^RUT", "name": "Russell 2000", "description": "Small-cap"},
                {"symbol": "^VIX", "name": "VIX", "description": "Volatility"},
            ],
        },
        "settings": {"historical_days": 252},
    }
    return fake_yaml


def _make_fake_yfinance():
    fake_yf = types.ModuleType("yfinance")
    fake_yf.download = MagicMock(name="yf.download", return_value=FakeBatchDF({}))
    fake_yf.Ticker = MagicMock(name="yf.Ticker")
    return fake_yf


def _make_fake_yf_retry():
    mod = types.ModuleType("shared.yf_retry")

    def passthrough_retry(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    mod.with_429_retry = passthrough_retry
    return mod


def _make_fake_yf_session():
    mod = types.ModuleType("shared.yf_session")
    mod.make_session = lambda: "FAKE_SESSION"
    return mod


def _make_fake_cache_manager():
    mod = types.ModuleType("shared.cache_manager")

    class FakeCachedDataFetcher:
        def __init__(self, *, cache_dir):
            self.cache_dir = cache_dir

        def fetch_prices(self, *, tickers, period, cache_name):
            return FakeBatchDF({})

    mod.CachedDataFetcher = FakeCachedDataFetcher
    return mod


def _make_fake_fetch_guard():
    mod = types.ModuleType("shared.fetch_guard")
    mod.assert_enough_succeeded = MagicMock(name="assert_enough_succeeded")
    return mod


def _make_fake_utils():
    mod = types.ModuleType("utils")
    mod.calculate_all_technical_indicators = lambda s: {}
    mod.calculate_returns = lambda s: {}
    mod.calculate_52_week_metrics = lambda s: {}
    mod.calculate_statistics = lambda s: {}
    mod.calculate_pivot_points = lambda **kw: {}
    mod.dataframe_to_daily_records = lambda df: []
    mod.get_current_snapshot = lambda df: {}
    mod.create_index_metadata = lambda **kw: {}
    mod.save_json = lambda data, path: None
    mod.determine_market_sentiment = lambda a, b: "neutral"
    mod.format_timestamp = lambda dt=None: "2026-05-21T00:00:00Z"
    mod.format_date = lambda dt=None: "2026-05-21"
    mod.safe_round = lambda v, d=2: v
    return mod


def _make_fake_shared_pkg():
    """The fetch script does `from shared.cache_manager import ...`. Make sure
    `shared` is a package marker so submodule imports work."""
    pkg = types.ModuleType("shared")
    pkg.__path__ = [str(_REPO / "shared")]
    return pkg


def _load_target():
    """Load fetch_us_major with all heavy deps stubbed. Returns (mod, fakes_dict)."""
    fake_pd = _make_fake_pandas()
    fake_yaml = _make_fake_yaml()
    fake_yf = _make_fake_yfinance()
    fake_yf_retry = _make_fake_yf_retry()
    fake_yf_session = _make_fake_yf_session()
    fake_cm = _make_fake_cache_manager()
    fake_guard = _make_fake_fetch_guard()
    fake_utils = _make_fake_utils()
    fake_shared = _make_fake_shared_pkg()

    sys.modules["pandas"] = fake_pd
    sys.modules["yaml"] = fake_yaml
    sys.modules["yfinance"] = fake_yf
    sys.modules["shared"] = fake_shared
    sys.modules["shared.yf_retry"] = fake_yf_retry
    sys.modules["shared.yf_session"] = fake_yf_session
    sys.modules["shared.cache_manager"] = fake_cm
    sys.modules["shared.fetch_guard"] = fake_guard
    sys.modules["utils"] = fake_utils

    spec = importlib.util.spec_from_file_location("fetch_us_major", _TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_us_major"] = mod
    spec.loader.exec_module(mod)

    return mod, {
        "pd": fake_pd,
        "yf": fake_yf,
        "yf_retry": fake_yf_retry,
        "guard": fake_guard,
        "utils": fake_utils,
    }


@pytest.fixture()
def mod_and_fakes():
    sys.modules.pop("fetch_us_major", None)
    return _load_target()


# ---------------------------------------------------------------------------
# Tests for _batch_download_indices
# ---------------------------------------------------------------------------


SIX_SYMBOLS = ["^GSPC", "^DJI", "^IXIC", "^NDX", "^RUT", "^VIX"]


class TestBatchDownloadIndices:

    def test_single_yf_download_call_for_all_six_symbols(self, mod_and_fakes):
        """One yf.download call covers all 6 core indices."""
        mod, fakes = mod_and_fakes
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS}
        fakes["yf"].download.reset_mock()
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        result = mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        assert fakes["yf"].download.call_count == 1
        call_kwargs = fakes["yf"].download.call_args.kwargs
        # symbols can be passed positionally or as kwarg "tickers"
        passed_tickers = call_kwargs.get("tickers")
        if passed_tickers is None:
            passed_tickers = fakes["yf"].download.call_args.args[0]
        assert list(passed_tickers) == SIX_SYMBOLS
        assert set(result.keys()) == set(SIX_SYMBOLS)

    def test_multiindex_extraction_returns_per_ticker_df(self, mod_and_fakes):
        """Per-ticker DataFrames are extracted via df[symbol] from MultiIndex."""
        mod, fakes = mod_and_fakes
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        result = mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        for sym in SIX_SYMBOLS:
            assert result[sym] is per_ticker[sym], (
                f"Expected df[{sym}] to be the per-ticker frame"
            )

    def test_missing_symbol_returns_none_or_empty(self, mod_and_fakes):
        """A symbol absent from the MultiIndex response yields a None/empty entry."""
        mod, fakes = mod_and_fakes
        partial = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS[:5]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)

        result = mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        missing = SIX_SYMBOLS[5]
        # Missing symbol must not raise; value should be falsy (None or empty)
        assert missing in result
        val = result[missing]
        assert val is None or getattr(val, "empty", False) or len(val) == 0

    def test_with_429_retry_wraps_yf_download(self, mod_and_fakes, monkeypatch):
        """yf.download is called through with_429_retry, not directly."""
        mod, fakes = mod_and_fakes
        retry_calls = []

        def tracking_retry(fn, *args, **kwargs):
            retry_calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        monkeypatch.setattr(mod, "with_429_retry", tracking_retry, raising=False)

        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        assert len(retry_calls) == 1
        wrapped_fn = retry_calls[0][0]
        # The function passed to with_429_retry should be yf.download
        assert wrapped_fn is fakes["yf"].download

    def test_session_passed_to_yf_download(self, mod_and_fakes):
        """The YF_SESSION is passed to yf.download via the session kwarg."""
        mod, fakes = mod_and_fakes
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        kwargs = fakes["yf"].download.call_args.kwargs
        assert kwargs.get("session") == mod.YF_SESSION
        assert kwargs.get("group_by") == "ticker"

    def test_single_ticker_response_is_handled(self, mod_and_fakes):
        """If the response has flat (non-MultiIndex) columns, the single ticker is still returned."""
        mod, fakes = mod_and_fakes
        flat_df = FakeBatchDF({}, multiindex=False)
        # Mark non-empty so the function treats it as real data
        flat_df.empty = False
        fakes["yf"].download.return_value = flat_df

        result = mod._batch_download_indices(["^GSPC"], period="1y")

        assert "^GSPC" in result
        # For single-ticker case, the entire (flat) frame IS the per-ticker frame.
        assert result["^GSPC"] is flat_df

    def test_empty_response_returns_none_for_each_symbol(self, mod_and_fakes):
        """If yf.download returns an empty/None df, every symbol entry is None/empty."""
        mod, fakes = mod_and_fakes
        fakes["yf"].download.return_value = None

        result = mod._batch_download_indices(SIX_SYMBOLS, period="1y")

        assert set(result.keys()) == set(SIX_SYMBOLS)
        for sym in SIX_SYMBOLS:
            val = result[sym]
            assert val is None or getattr(val, "empty", False)


# ---------------------------------------------------------------------------
# Tests verifying assert_enough_succeeded is called with the correct count
# ---------------------------------------------------------------------------


class TestAssertEnoughSucceededWiring:

    def test_snapshot_calls_assert_with_success_count(self, mod_and_fakes, monkeypatch):
        """create_snapshot_json calls assert_enough_succeeded with the count of non-empty
        per-ticker frames extracted from the batch."""
        mod, fakes = mod_and_fakes

        # 4 successes, 2 misses
        partial = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS[:4]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)

        # Return a snapshot dict so the existing code path can keep going
        fakes["utils"].get_current_snapshot = lambda df: {
            "current_price": 100, "daily_change": 1, "daily_change_percent": 1,
            "volume": 1000, "day_high": 101, "day_low": 99, "day_open": 100,
        }
        # Need to also replace the bound import in the module's namespace
        monkeypatch.setattr(mod, "get_current_snapshot", fakes["utils"].get_current_snapshot, raising=False)

        guard = fakes["guard"].assert_enough_succeeded
        guard.reset_mock()

        mod.create_snapshot_json()

        assert guard.call_count == 1
        kwargs = guard.call_args.kwargs
        assert kwargs.get("total") == 6
        assert kwargs.get("successful") == 4

    def test_historical_calls_assert_with_success_count(self, mod_and_fakes, monkeypatch):
        """create_historical_json calls assert_enough_succeeded with the count of
        non-empty per-ticker frames."""
        mod, fakes = mod_and_fakes

        # 5 successes, 1 miss
        partial = {s: FakePerTickerDF(s, rows=252) for s in SIX_SYMBOLS[:5]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)

        guard = fakes["guard"].assert_enough_succeeded
        guard.reset_mock()

        mod.create_historical_json()

        assert guard.call_count == 1
        kwargs = guard.call_args.kwargs
        assert kwargs.get("total") == 6
        assert kwargs.get("successful") == 5


class TestSnapshotNullCloseHandling:

    def test_snapshot_uses_close_sanitized_frame_for_current_values(self, mod_and_fakes, monkeypatch):
        """Trailing rows with no Close are removed before deriving snapshot values."""
        mod, fakes = mod_and_fakes

        per_ticker = {s: FakeTickerDFWithTrailingEmptyClose(s, rows=252) for s in SIX_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        seen_cleaned_flags = []

        def snapshot_from_df(df):
            seen_cleaned_flags.append(getattr(df, "cleaned", False))
            return {
                "current_price": 105,
                "daily_change": 4,
                "daily_change_percent": 3.96,
                "volume": 2000,
                "day_high": 106,
                "day_low": 100,
                "day_open": 101,
            }

        monkeypatch.setattr(mod, "get_current_snapshot", snapshot_from_df, raising=False)

        mod.create_snapshot_json()

        assert seen_cleaned_flags == [True, True, True, True, True, True]


# ---------------------------------------------------------------------------
# Sectors variant — fetch_sectors.py (Issue 002)
# ---------------------------------------------------------------------------


_SECTORS_TARGET = _REPO / "majorindexes" / "fetch_sectors.py"

SECTOR_SYMBOLS = [
    "XLK", "XLV", "XLF", "XLY", "XLI", "XLP", "XLE", "XLB", "XLC", "XLU", "XLRE",
]


def _make_fake_yaml_sectors():
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda f: {
        "us_sector_indices": {
            "description": "11 GICS sectors via Select Sector SPDR ETFs",
            "output_files": {
                "snapshot": "us_sector_indices.json",
                "historical": "us_sector_indices_historical.json",
            },
            "benchmark": "^GSPC",
            "sectors": [
                {"symbol": s, "name": f"{s} Fund", "sector_name": s,
                 "gics_code": "00", "description": f"{s} desc"}
                for s in SECTOR_SYMBOLS
            ],
        },
        "settings": {"historical_days": 252},
    }
    return fake_yaml


def _make_fake_utils_sectors():
    mod = types.ModuleType("utils")
    mod.calculate_all_technical_indicators = lambda s: {}
    mod.calculate_returns = lambda s: {}
    mod.calculate_52_week_metrics = lambda s: {}
    mod.calculate_statistics = lambda s: {}
    mod.calculate_pivot_points = lambda **kw: {}
    mod.dataframe_to_daily_records = lambda df: []
    mod.get_current_snapshot = lambda df: {}
    mod.get_current_snapshot_from_info = lambda info, df: {}
    mod.create_index_metadata = lambda **kw: {}
    mod.save_json = lambda data, path: None
    mod.rank_by_performance = lambda data, key: []
    mod.format_timestamp = lambda dt=None: "2026-05-21T00:00:00Z"
    mod.format_date = lambda dt=None: "2026-05-21"
    mod.safe_round = lambda v, d=2: v
    return mod


def _load_sectors_target():
    """Load fetch_sectors with all heavy deps stubbed. Returns (mod, fakes_dict)."""
    fake_pd = _make_fake_pandas()
    fake_yaml = _make_fake_yaml_sectors()
    fake_yf = _make_fake_yfinance()
    fake_yf_retry = _make_fake_yf_retry()
    fake_yf_session = _make_fake_yf_session()
    fake_cm = _make_fake_cache_manager()
    fake_guard = _make_fake_fetch_guard()
    fake_utils = _make_fake_utils_sectors()
    fake_shared = _make_fake_shared_pkg()

    sys.modules["pandas"] = fake_pd
    sys.modules["yaml"] = fake_yaml
    sys.modules["yfinance"] = fake_yf
    sys.modules["shared"] = fake_shared
    sys.modules["shared.yf_retry"] = fake_yf_retry
    sys.modules["shared.yf_session"] = fake_yf_session
    sys.modules["shared.cache_manager"] = fake_cm
    sys.modules["shared.fetch_guard"] = fake_guard
    sys.modules["utils"] = fake_utils

    spec = importlib.util.spec_from_file_location("fetch_sectors", _SECTORS_TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_sectors"] = mod
    spec.loader.exec_module(mod)

    return mod, {
        "pd": fake_pd,
        "yf": fake_yf,
        "yf_retry": fake_yf_retry,
        "guard": fake_guard,
        "utils": fake_utils,
    }


@pytest.fixture()
def mod_and_fakes_sectors():
    sys.modules.pop("fetch_sectors", None)
    return _load_sectors_target()


class TestBatchDownloadSectors:

    def test_single_yf_download_call_for_all_eleven_symbols(self, mod_and_fakes_sectors):
        """One yf.download call covers all 11 sector ETFs."""
        mod, fakes = mod_and_fakes_sectors
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SECTOR_SYMBOLS}
        fakes["yf"].download.reset_mock()
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        result = mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        assert fakes["yf"].download.call_count == 1
        call_kwargs = fakes["yf"].download.call_args.kwargs
        passed_tickers = call_kwargs.get("tickers")
        if passed_tickers is None:
            passed_tickers = fakes["yf"].download.call_args.args[0]
        assert list(passed_tickers) == SECTOR_SYMBOLS
        assert set(result.keys()) == set(SECTOR_SYMBOLS)

    def test_multiindex_extraction_returns_per_ticker_df(self, mod_and_fakes_sectors):
        """Per-ticker DataFrames are extracted via df[symbol] from MultiIndex."""
        mod, fakes = mod_and_fakes_sectors
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SECTOR_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        result = mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        for sym in SECTOR_SYMBOLS:
            assert result[sym] is per_ticker[sym], (
                f"Expected df[{sym}] to be the per-ticker frame"
            )

    def test_missing_symbol_returns_none_or_empty(self, mod_and_fakes_sectors):
        """A sector ETF absent from the MultiIndex response yields a None/empty entry."""
        mod, fakes = mod_and_fakes_sectors
        partial = {s: FakePerTickerDF(s, rows=252) for s in SECTOR_SYMBOLS[:9]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)

        result = mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        for missing in SECTOR_SYMBOLS[9:]:
            assert missing in result
            val = result[missing]
            assert val is None or getattr(val, "empty", False) or len(val) == 0

    def test_with_429_retry_wraps_yf_download(self, mod_and_fakes_sectors, monkeypatch):
        """yf.download is called through with_429_retry, not directly."""
        mod, fakes = mod_and_fakes_sectors
        retry_calls = []

        def tracking_retry(fn, *args, **kwargs):
            retry_calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        monkeypatch.setattr(mod, "with_429_retry", tracking_retry, raising=False)

        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SECTOR_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        assert len(retry_calls) == 1
        wrapped_fn = retry_calls[0][0]
        assert wrapped_fn is fakes["yf"].download

    def test_session_and_group_by_passed_to_yf_download(self, mod_and_fakes_sectors):
        """The YF_SESSION and group_by='ticker' are passed to yf.download."""
        mod, fakes = mod_and_fakes_sectors
        per_ticker = {s: FakePerTickerDF(s, rows=252) for s in SECTOR_SYMBOLS}
        fakes["yf"].download.return_value = FakeBatchDF(per_ticker)

        mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        kwargs = fakes["yf"].download.call_args.kwargs
        assert kwargs.get("session") == mod.YF_SESSION
        assert kwargs.get("group_by") == "ticker"

    def test_empty_response_returns_none_for_each_symbol(self, mod_and_fakes_sectors):
        """If yf.download returns None, every symbol entry is None/empty."""
        mod, fakes = mod_and_fakes_sectors
        fakes["yf"].download.return_value = None

        result = mod._batch_download_sectors(SECTOR_SYMBOLS, period="1y")

        assert set(result.keys()) == set(SECTOR_SYMBOLS)
        for sym in SECTOR_SYMBOLS:
            val = result[sym]
            assert val is None or getattr(val, "empty", False)


class TestSectorsAssertEnoughSucceededWiring:

    def test_snapshot_exits_when_all_sector_downloads_empty(self, mod_and_fakes_sectors):
        """An all-empty sector batch trips assert_enough_succeeded before saving."""
        mod, fakes = mod_and_fakes_sectors
        fakes["yf"].download.return_value = FakeBatchDF({})

        guard = fakes["guard"].assert_enough_succeeded
        guard.reset_mock()

        def fail_when_empty(*, successful, total, label):
            if successful == 0:
                raise SystemExit(1)

        guard.side_effect = fail_when_empty

        with pytest.raises(SystemExit) as exc:
            mod.create_snapshot_json()

        assert exc.value.code == 1
        kwargs = guard.call_args.kwargs
        assert kwargs.get("total") == 11
        assert kwargs.get("successful") == 0

    def test_snapshot_calls_assert_with_success_count(self, mod_and_fakes_sectors, monkeypatch):
        """create_snapshot_json calls assert_enough_succeeded with the count of non-empty
        per-ticker frames extracted from the batch and writes successful sectors."""
        mod, fakes = mod_and_fakes_sectors

        # 7 successes, 4 misses
        partial = {s: FakeProcessableTickerDF(s, rows=252) for s in SECTOR_SYMBOLS[:7]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)
        saved = {}

        def capture_save_json(data, path):
            saved["data"] = data
            saved["path"] = path

        monkeypatch.setattr(mod, "save_json", capture_save_json, raising=False)
        monkeypatch.setattr(
            mod,
            "get_current_snapshot",
            lambda df: {
                "current_price": 101,
                "daily_change": 1,
                "daily_change_percent": 1,
                "volume": 1000,
            },
            raising=False,
        )
        monkeypatch.setattr(mod, "calculate_returns", lambda s: {"1_month_percent": 2}, raising=False)
        monkeypatch.setattr(mod, "calculate_52_week_metrics", lambda s: {"52_week_high": 110}, raising=False)

        guard = fakes["guard"].assert_enough_succeeded
        guard.reset_mock()

        mod.create_snapshot_json()

        assert guard.call_count == 1
        kwargs = guard.call_args.kwargs
        assert kwargs.get("total") == 11
        assert kwargs.get("successful") == 7
        assert set(saved["data"]["sectors"].keys()) == set(SECTOR_SYMBOLS[:7])
        assert saved["data"]["sectors"]["XLK"]["current_price"] == 101

    def test_historical_calls_assert_with_success_count(self, mod_and_fakes_sectors, monkeypatch):
        """create_historical_json calls assert_enough_succeeded with the count of
        non-empty per-ticker frames and writes successful sectors."""
        mod, fakes = mod_and_fakes_sectors

        # 9 successes, 2 misses
        partial = {s: FakeProcessableTickerDF(s, rows=252) for s in SECTOR_SYMBOLS[:9]}
        fakes["yf"].download.return_value = FakeBatchDF(partial)
        saved = {}

        def capture_save_json(data, path):
            saved["data"] = data
            saved["path"] = path

        monkeypatch.setattr(mod, "save_json", capture_save_json, raising=False)
        monkeypatch.setattr(mod, "dataframe_to_daily_records", lambda df: [{"date": "2026-05-21"}], raising=False)
        monkeypatch.setattr(mod, "calculate_statistics", lambda s: {}, raising=False)

        guard = fakes["guard"].assert_enough_succeeded
        guard.reset_mock()

        mod.create_historical_json()

        assert guard.call_count == 1
        kwargs = guard.call_args.kwargs
        assert kwargs.get("total") == 11
        assert kwargs.get("successful") == 9
        assert set(saved["data"]["sectors"].keys()) == set(SECTOR_SYMBOLS[:9])
        assert saved["data"]["sectors"]["XLK"]["data"] == [{"date": "2026-05-21"}]
