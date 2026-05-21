"""Tests for shared.yf_retry and shared.yf_session helpers.

The modules are loaded directly via importlib to bypass shared/__init__.py,
which eagerly imports heavy dependencies (pandas, yfinance) that are not
required to exercise these tiny helpers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


def test_returns_value_on_first_success(monkeypatch):
    calls = {"n": 0}
    sleep_calls = {"n": 0}

    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: sleep_calls.__setitem__("n", sleep_calls["n"] + 1))

    def fn():
        calls["n"] += 1
        return 42

    assert with_429_retry(fn) == 42
    assert calls["n"] == 1
    assert sleep_calls["n"] == 0


def test_retries_on_ratelimit_then_succeeds(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: None)

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeRateLimit("first attempt")
        return 42

    assert with_429_retry(fn) == 42
    assert calls["n"] == 2


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


def test_matches_429_in_message(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(yf_retry.time, "sleep", lambda _s: None)

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"

    assert with_429_retry(fn) == "ok"
    assert calls["n"] == 2


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
