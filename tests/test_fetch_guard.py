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
    captured = capsys.readouterr()
    assert "snapshot" in captured.err
    assert "0/5" in captured.err
    assert "refusing" in captured.err


def test_at_least_one_successful_returns_none():
    assert assert_enough_succeeded(1, 5, label="snapshot") is None


def test_total_zero_is_noop_even_when_successful_zero():
    # Nothing was attempted; nothing to guard.
    assert assert_enough_succeeded(0, 0, label="snapshot") is None


def test_all_successful_returns_none():
    assert assert_enough_succeeded(7, 7, label="historical") is None


def test_label_is_keyword_only_required():
    with pytest.raises(TypeError):
        assert_enough_succeeded(1, 5)  # type: ignore[call-arg]
