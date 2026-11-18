"""Regression: the Finnhub API key must never reach spgrowth's logs.

A requests exception's message includes the request URL. When the key was
built into the URL as ``token=...`` and the handler printed ``{e}``, a
network error wrote the key to the workflow log. The key now travels in the
X-Finnhub-Token header and warnings print only the exception type and status.

Every test mocks ``requests.get``; no network.
"""
from __future__ import annotations

import logging

import pytest
import requests

pytest.importorskip("secedgar")  # heavy transitive dep; present in CI

from spgrowth import fetch_sp_growth as sg  # noqa: E402

KEY = "SECRETKEY123456"

FINNHUB_CALLS = [
    lambda: sg.finnhub_quarterly_financials("AAA", KEY),
    lambda: sg.finnhub_as_reported_quarterly_financials("AAA", KEY),
    lambda: sg.finnhub_annual_financials("AAA", KEY),
    lambda: sg.finnhub_as_reported_annual_financials("AAA", KEY),
]
IDS = ["quarterly", "as-reported-quarterly", "annual", "as-reported-annual"]


def _raising_get(exc_type, calls):
    """Fake requests.get that fails like requests does: the message carries the full URL."""

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        full_url = requests.Request("GET", url, params=params).prepare().url
        calls.append({"url": full_url, "headers": dict(headers or {})})
        response = None
        if exc_type is requests.HTTPError:
            response = requests.Response()
            response.status_code = 429
            response.url = full_url
        raise exc_type(
            f"HTTPSConnectionPool(host='finnhub.io', port=443): Max retries exceeded with url: {full_url}",
            response=response,
        )

    return fake_get


@pytest.mark.parametrize("exc_type", [requests.ConnectionError, requests.HTTPError])
@pytest.mark.parametrize("call", FINNHUB_CALLS, ids=IDS)
def test_finnhub_errors_never_log_the_key(monkeypatch, capsys, caplog, call, exc_type):
    calls = []
    monkeypatch.setattr(sg.requests, "get", _raising_get(exc_type, calls))
    caplog.set_level(logging.DEBUG)

    df = call()

    assert df.empty
    assert calls, "requests.get was not called"
    out, err = capsys.readouterr()
    assert KEY not in out
    assert KEY not in err
    assert KEY not in caplog.text


@pytest.mark.parametrize("call", FINNHUB_CALLS, ids=IDS)
def test_finnhub_key_sent_in_header_not_url(monkeypatch, call):
    calls = []
    monkeypatch.setattr(sg.requests, "get", _raising_get(requests.ConnectionError, calls))

    call()

    for c in calls:
        assert KEY not in c["url"]
        assert c["headers"].get("X-Finnhub-Token") == KEY


def test_as_reported_warning_names_type_and_status(monkeypatch, capsys):
    monkeypatch.setattr(sg.requests, "get", _raising_get(requests.HTTPError, []))

    sg.finnhub_as_reported_annual_financials("AAA", KEY)

    out = capsys.readouterr().out
    assert "HTTPError (HTTP 429)" in out
