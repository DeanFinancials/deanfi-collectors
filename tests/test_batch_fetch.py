"""Batched Yahoo downloads in majorindexes/fetch_us_major.py and fetch_sectors.py.

Only the network boundary (yf.download / yf.Ticker) is faked. Real pandas, the
real majorindexes utils, the real publication guard and the real save_json run,
and output is written to tmp_path so tests assert on what would be published.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

import shared.yf_retry as retry_module

MAJORINDEXES = Path(__file__).resolve().parent.parent / "majorindexes"

# (module, batch splitter, configured-universe attribute, output body key)
MODULES = [
    ("fetch_us_major", "_batch_download_indices", "INDICES", "indices"),
    ("fetch_sectors", "_batch_download_sectors", "SECTORS", "sectors"),
]


def _exec(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ohlcv(closes):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": 1000.0}
    ).set_index(pd.bdate_range("2026-01-02", periods=len(closes)))


def batch(frames: dict) -> pd.DataFrame:
    """Shape of yf.download(group_by='ticker'): columns are (ticker, field)."""
    return pd.concat(frames, axis=1) if frames else pd.DataFrame()


@pytest.fixture
def load(monkeypatch, tmp_path):
    """Load a collector with Yahoo replaced by a canned batch response."""
    utils = _exec("utils", MAJORINDEXES / "utils.py")
    monkeypatch.setitem(sys.modules, "utils", utils)
    # Debian's system pytz lacks the legacy US/Eastern link that pip's pytz bundles.
    real_timezone = utils.pytz.timezone
    monkeypatch.setattr(utils.pytz, "timezone",
                        lambda name: real_timezone("America/New_York" if name == "US/Eastern" else name))
    monkeypatch.setattr(retry_module.time, "sleep", lambda _s: None)

    def _load(module_name, response=None):
        module = _exec(f"{module_name}_under_test", MAJORINDEXES / f"{module_name}.py")
        download = Mock(return_value=response)
        monkeypatch.setattr(module.yf, "download", download)
        monkeypatch.setattr(module.yf, "Ticker", Mock(side_effect=RuntimeError("offline")))
        monkeypatch.setattr(module, "SCRIPT_DIR", str(tmp_path))
        universe = {m[0]: m[2] for m in MODULES}[module_name]
        return module, download, [entry["symbol"] for entry in getattr(module, universe)]

    return _load


def published(tmp_path):
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text())


@pytest.mark.parametrize("module_name,splitter,_attr,_key", MODULES)
def test_one_download_is_split_per_ticker(load, module_name, splitter, _attr, _key):
    module, download, symbols = load(module_name)
    frames = {s: ohlcv([100, 101]) for s in symbols[:-1]}
    download.return_value = batch(frames)

    result = getattr(module, splitter)(symbols, period="1y")

    assert download.call_count == 1
    assert download.call_args.kwargs["group_by"] == "ticker"  # split below relies on it
    for symbol in symbols[:-1]:
        pd.testing.assert_frame_equal(result[symbol], frames[symbol], check_freq=False)
    assert result[symbols[-1]] is None


@pytest.mark.parametrize("module_name,splitter,_attr,_key", MODULES)
@pytest.mark.parametrize("response", [None, pd.DataFrame()], ids=["none", "empty"])
def test_empty_download_yields_no_frames(load, module_name, splitter, _attr, _key, response):
    module, _, symbols = load(module_name, response)
    assert getattr(module, splitter)(symbols, period="1y") == {s: None for s in symbols}


@pytest.mark.parametrize("module_name,splitter,_attr,_key", MODULES)
def test_single_symbol_flat_response_is_kept(load, module_name, splitter, _attr, _key):
    frame = ohlcv([100, 101])
    module, _, symbols = load(module_name, frame)
    assert getattr(module, splitter)(symbols[:1], period="1y") == {symbols[0]: frame}


@pytest.mark.parametrize("module_name,_splitter,_attr,key", MODULES)
@pytest.mark.parametrize("builder", ["create_snapshot_json", "create_historical_json"])
def test_partial_download_publishes_only_downloaded_symbols(load, tmp_path, module_name, _splitter, _attr, key, builder):
    module, download, symbols = load(module_name)
    ok = symbols[:3]
    download.return_value = batch({s: ohlcv(np.linspace(100, 130, 30)) for s in ok})

    getattr(module, builder)()

    body = published(tmp_path)[key]
    assert sorted(body) == sorted(ok)
    if builder == "create_snapshot_json":
        assert all(math.isfinite(row["current_price"]) and row["current_price"] > 0 for row in body.values())


@pytest.mark.parametrize("module_name,_splitter,_attr,_key", MODULES)
@pytest.mark.parametrize("builder", ["create_snapshot_json", "create_historical_json"])
def test_nothing_downloaded_publishes_nothing(load, tmp_path, module_name, _splitter, _attr, _key, builder):
    module, _, _ = load(module_name, pd.DataFrame())
    with pytest.raises(SystemExit) as exc:
        getattr(module, builder)()
    assert exc.value.code == 1
    assert list(tmp_path.iterdir()) == []


def test_us_major_snapshot_ignores_trailing_row_without_close(load, tmp_path):
    module, download, symbols = load("fetch_us_major")
    download.return_value = batch({s: ohlcv([100, 101, np.nan]) for s in symbols})

    module.create_snapshot_json()

    indices = published(tmp_path)["indices"]
    assert sorted(indices) == sorted(symbols)
    assert {row["current_price"] for row in indices.values()} == {101}


@pytest.mark.parametrize("module_name,_splitter,_attr,_key", [
    pytest.param(*MODULES[0], marks=pytest.mark.xfail(
        strict=True,
        reason="fetch_us_major guards on downloaded frames, not usable rows, so it "
               "publishes an empty `indices` object (caught later only by validate_snapshots)")),
    MODULES[1],
])
def test_snapshot_with_only_unusable_closes_publishes_nothing(load, tmp_path, module_name, _splitter, _attr, _key):
    module, download, symbols = load(module_name)
    download.return_value = batch({s: ohlcv([100, 0]) for s in symbols})
    with pytest.raises(SystemExit):
        module.create_snapshot_json()
    assert list(tmp_path.iterdir()) == []
