"""fetch_commodities paces Yahoo calls between symbols without raising.

`from utils import *` used to import datetime.time over the time module, so
`time.sleep(0.3)` raised AttributeError after each symbol: every symbol logged
an error and no pacing happened. Only the network and the sleep are faked.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "majorindexes" / "fetch_commodities.py"


def _exec(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Ticker:
    def __init__(self, symbol, session=None):
        self.info = {"regularMarketPrice": 101.0, "regularMarketPreviousClose": 100.0,
                     "regularMarketChange": 1.0, "regularMarketChangePercent": 1.0}


def _frame(_symbol, period="1y", cache_dir=None):
    closes = 100 * np.exp(np.cumsum(np.full(260, 0.001)))
    return pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": 1000.0},
        index=pd.bdate_range(end="2026-11-17", periods=len(closes)),
    )


@pytest.fixture
def commodities(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "utils", _exec("utils_majorindexes_pacing", REPO / "majorindexes" / "utils.py"))
    module = _exec("fetch_commodities_pacing_under_test", SCRIPT)
    monkeypatch.setattr(module.yf, "Ticker", _Ticker)
    monkeypatch.setattr(module, "fetch_index_data", _frame)
    monkeypatch.setattr(module, "SCRIPT_DIR", str(tmp_path))
    module.args = argparse.Namespace(cache_dir=None)
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return module, sleeps


@pytest.mark.parametrize("step", ["create_snapshot_json", "create_historical_json"])
def test_per_symbol_loop_sleeps_without_error(commodities, capsys, step):
    module, sleeps = commodities
    result = getattr(module, step)()
    out = capsys.readouterr().out
    assert "❌" not in out, out
    assert len(result["indices"]) == len(module.INDICES)
    assert sleeps == [0.3] * len(module.INDICES)
