"""Tests for shared.fetch_guard.assert_enough_succeeded.

The module is loaded directly via importlib to bypass shared/__init__.py,
which eagerly imports heavy dependencies (pandas, yfinance) that are not
required to exercise this tiny pure-stdlib helper.
"""
import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "shared" / "fetch_guard.py"
_spec = importlib.util.spec_from_file_location("fetch_guard", _MODULE_PATH)
fetch_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_guard)
assert_enough_succeeded = fetch_guard.assert_enough_succeeded


def test_zero_successful_with_positive_total_exits_one(capsys):
    with pytest.raises(SystemExit) as excinfo:
        assert_enough_succeeded(0, 5, label="snapshot")
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "snapshot" in err and "0/5" in err  # which output, how many fetched


@pytest.mark.parametrize("successful,total", [(1, 5), (7, 7), (0, 0)])
def test_any_success_or_nothing_attempted_allows_publish(successful, total):
    assert assert_enough_succeeded(successful, total, label="snapshot") is None
