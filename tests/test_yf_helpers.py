"""Tests for shared.yf_retry and shared.yf_session helpers.

The modules are loaded directly via importlib to bypass shared/__init__.py,
which eagerly imports yfinance and the cache layer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

_SHARED = Path(__file__).resolve().parent.parent / "shared"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SHARED / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


yf_retry = _load("yf_retry", "yf_retry.py")
yf_session = _load("yf_session", "yf_session.py")

with_429_retry = yf_retry.with_429_retry
make_session = yf_session.make_session


class FakeRateLimit(Exception):
    """Custom exception whose class name contains 'RateLimit'."""
    pass


# -------------------- with_429_retry --------------------


@pytest.mark.parametrize("error", [FakeRateLimit("rate limited"), RuntimeError("HTTP 429 Too Many Requests")],
                         ids=["ratelimit-class", "429-message"])
def test_retries_rate_limit_then_succeeds(monkeypatch, error):
    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: None)
    fn = Mock(side_effect=[error, 42])
    assert with_429_retry(fn) == 42
    assert fn.call_count == 2


def test_raises_after_exhausting_retries(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: None)

    def fn():
        calls["n"] += 1
        raise FakeRateLimit("always fails")

    with pytest.raises(FakeRateLimit):
        with_429_retry(fn, retries=1)
    assert calls["n"] == 2  # initial + 1 retry


def test_does_not_retry_on_other_exception(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: None)

    def fn():
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_429_retry(fn)
    assert calls["n"] == 1


@pytest.mark.parametrize("empty", [None, pd.DataFrame(), pd.DataFrame({"Close": [float("nan")]})],
                         ids=["none", "empty", "all-nan"])
def test_swallowed_yahoo_errors_retry_then_recover(monkeypatch, empty):
    """yfinance swallows some failures and returns empty frames; retry_empty retries them."""
    sleep = Mock()
    monkeypatch.setattr(yf_retry.time, "sleep", sleep)
    valid = pd.DataFrame({"Close": [100.0]})
    download = Mock(side_effect=[empty, valid])
    assert with_429_retry(download, retry_empty=True) is valid
    assert download.call_count == 2
    sleep.assert_called_once()


def test_empty_retry_exhaustion_returns_empty_for_publication_guard(monkeypatch):
    monkeypatch.setattr(yf_retry.time, "sleep", Mock())
    empty = pd.DataFrame()
    download = Mock(return_value=empty)
    assert with_429_retry(download, retry_empty=True) is empty
    assert download.call_count == 2


@pytest.mark.parametrize("retry_empty", [False, True])
def test_valid_and_partial_responses_are_not_retried(monkeypatch, retry_empty):
    sleep = Mock()
    monkeypatch.setattr(yf_retry.time, "sleep", sleep)
    frame = pd.DataFrame({"AAA": [100.0], "BBB": [float("nan")]})
    download = Mock(return_value=frame)
    assert with_429_retry(download, retry_empty=retry_empty) is frame
    download.assert_called_once_with()
    sleep.assert_not_called()


# -------------------- make_session --------------------


def test_make_session_returns_none_when_curl_cffi_missing(monkeypatch):
    """Force ImportError by inserting None into sys.modules for curl_cffi."""
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", None)

    # Reload module so its try/except runs again
    fresh = _load("yf_session_fresh", "yf_session.py")
    assert fresh.make_session() is None


def test_make_session_returns_session_when_curl_cffi_available():
    pytest.importorskip("curl_cffi")
    fresh = _load("yf_session_fresh2", "yf_session.py")
    sess = fresh.make_session()
    assert sess is not None
    assert hasattr(sess, "get")
