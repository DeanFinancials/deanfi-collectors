"""Regression: API keys must never reach collector logs or error messages.

A requests exception's message includes the prepared URL. When a key travels
as a query parameter (Finnhub ``token``, Alpha Vantage ``apikey``, FRED
``api_key``) and a handler prints ``{e}``, a network or HTTP error writes the
key to the workflow log. Finnhub keys now travel in the X-Finnhub-Token header;
FRED and Alpha Vantage only accept query params, so their errors are redacted.

Every test mocks the HTTP call; no network.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
KEY = "FAKEKEY0123456789abc"


def _load(subdir: str, module: str):
    path = str(ROOT / subdir)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(module)


def _raising_get(exc_type, calls, status=503):
    """Fake GET that fails like requests does: the message carries the full prepared URL."""

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        full_url = requests.Request("GET", url, params=params).prepare().url
        calls.append({"url": full_url, "headers": dict(headers or {})})
        response = None
        if exc_type is requests.HTTPError:
            response = requests.Response()
            response.status_code = status
            response.url = full_url
            response._content = f'{{"error": "bad request {full_url}"}}'.encode()
        raise exc_type(f"Max retries exceeded with url: {full_url}", response=response)

    return fake_get


def _status_get(status, calls):
    """Fake GET returning an error status; raise_for_status embeds the full URL."""

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        full_url = requests.Request("GET", url, params=params).prepare().url
        calls.append({"url": full_url, "headers": dict(headers or {})})
        response = requests.Response()
        response.status_code = status
        response.url = full_url
        response.reason = "Error"
        response._content = f'{{"error_message": "failed for {full_url}"}}'.encode()
        return response

    return fake_get


# --- Finnhub clients: (name, factory returning (patch_target_obj, call)) ------------


def _analysttrends(monkeypatch):
    m = _load("analysttrends", "fetch_recommendation_trends")
    f = m.RecommendationTrendsFetcher(api_key=KEY)
    monkeypatch.setattr(f, "_rate_limit", lambda: None)
    return f.session, lambda: f.fetch_recommendation_trends("AAA", debug=True)


def _earningssurprises(monkeypatch):
    m = _load("earningssurprises", "fetch_earnings_surprises")
    monkeypatch.setenv("FINNHUB_API_KEY", KEY)
    f = m.EarningsSurprisesFetcher(str(ROOT / "earningssurprises" / "config.yml"))
    monkeypatch.setattr(f, "_rate_limit", lambda: None)
    return m.requests, lambda: f.fetch_ticker_earnings("AAA")


def _earningscalendar(monkeypatch):
    m = _load("earningscalendar", "fetch_earnings_calendar")
    monkeypatch.setenv("FINNHUB_API_KEY", KEY)
    f = m.EarningsCalendarFetcher(str(ROOT / "earningscalendar" / "config.yml"))
    monkeypatch.setattr(f, "_rate_limit", lambda: None)
    return m.requests, lambda: f.fetch_earnings_calendar("AAA", "2026-01-01", "2026-02-01")


def _dailynews_company(monkeypatch):
    m = _load("dailynews", "finnhub_client")
    c = m.FinnhubClient(api_key=KEY)
    return c.session, lambda: c.get_company_news("AAA", "2026-01-01", "2026-01-02")


def _dailynews_market(monkeypatch):
    m = _load("dailynews", "finnhub_client")
    c = m.FinnhubClient(api_key=KEY)

    def call():
        try:
            c.get_market_news()
        except Exception as e:  # propagated to the collector's caller, which prints it
            print(f"caller saw: {e}")

    return c.session, call


FINNHUB = {
    "analysttrends": _analysttrends,
    "earningssurprises": _earningssurprises,
    "earningscalendar": _earningscalendar,
    "dailynews-company": _dailynews_company,
    "dailynews-market": _dailynews_market,
}


def _assert_no_key(capsys, caplog):
    out, err = capsys.readouterr()
    assert KEY not in out
    assert KEY not in err
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [("raise", requests.ConnectionError), ("raise", requests.HTTPError), ("status", 401), ("status", 500)],
    ids=["ConnectionError", "HTTPError", "401", "500"],
)
@pytest.mark.parametrize("name", list(FINNHUB))
def test_finnhub_errors_never_log_the_key(monkeypatch, capsys, caplog, name, failure):
    caplog.set_level(logging.DEBUG)
    target, call = FINNHUB[name](monkeypatch)
    calls = []
    kind, arg = failure
    fake = _raising_get(arg, calls) if kind == "raise" else _status_get(arg, calls)
    monkeypatch.setattr(target, "get", fake)

    call()

    assert calls, "GET was not called"
    _assert_no_key(capsys, caplog)


@pytest.mark.parametrize("name", list(FINNHUB))
def test_finnhub_key_sent_in_header_not_url(monkeypatch, capsys, name):
    target, call = FINNHUB[name](monkeypatch)
    calls = []
    monkeypatch.setattr(target, "get", _raising_get(requests.ConnectionError, calls))

    call()

    assert calls
    for c in calls:
        assert KEY not in c["url"]
        assert c["headers"].get("X-Finnhub-Token") == KEY


# --- Alpha Vantage (etffundflows) ---------------------------------------------------


@pytest.mark.parametrize(
    "fake",
    [
        lambda calls: _raising_get(requests.ConnectionError, calls),
        lambda calls: _raising_get(requests.Timeout, calls),
    ],
    ids=["ConnectionError", "Timeout"],
)
def test_alphavantage_errors_never_log_the_key(monkeypatch, capsys, caplog, fake):
    m = _load("etffundflows", "fetch_etf_fund_flows")
    calls = []
    monkeypatch.setattr(m.requests, "get", fake(calls))

    assert m.alphavantage_etf_profile("SPY", KEY, 5) is None
    assert calls and KEY in calls[0]["url"]  # AV only takes the key as a query param
    _assert_no_key(capsys, caplog)


# --- FRED client and the economy collectors' top-level handlers ---------------------


FRED_FAILURES = {
    "ConnectionError": lambda calls: _raising_get(requests.ConnectionError, calls),
    "Timeout": lambda calls: _raising_get(requests.Timeout, calls),
    "400": lambda calls: _status_get(400, calls),
    "500": lambda calls: _status_get(500, calls),
}


def _fred_client(monkeypatch, failure, calls):
    m = _load("shared", "fred_client")
    client = m.FREDClient(api_key=KEY, rate_limit=0)
    monkeypatch.setattr(client.session, "get", FRED_FAILURES[failure](calls))
    return client


@pytest.mark.parametrize("failure", list(FRED_FAILURES))
def test_fred_error_message_has_no_key_but_keeps_context(monkeypatch, failure):
    calls = []
    client = _fred_client(monkeypatch, failure, calls)

    with pytest.raises(requests.RequestException) as excinfo:
        client.get_series_observations("GDPC1")

    assert calls and KEY in calls[0]["url"]  # FRED only takes the key as a query param
    exc = excinfo.value
    assert KEY not in str(exc)
    assert KEY not in repr(exc.args)
    chained = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    assert chained is None or KEY not in str(chained)
    if failure in ("400", "500"):
        assert isinstance(exc, requests.HTTPError)
        assert exc.response.status_code == int(failure)
        assert failure in str(exc) and "GDPC1" in str(exc)


@pytest.mark.parametrize("failure", list(FRED_FAILURES))
def test_fred_get_multiple_series_warning_has_no_key(monkeypatch, capsys, failure):
    client = _fred_client(monkeypatch, failure, [])

    result = client.get_multiple_series(["GDPC1"])

    assert result["GDPC1"].empty
    out, err = capsys.readouterr()
    assert "GDPC1" in out
    assert KEY not in out + err


ECONOMY = [
    ("consumercredit", "fetch_consumer_credit"),
    ("growthoutput", "fetch_growth_output"),
    ("housingaffordability", "fetch_housing_affordability"),
    ("inflationprices", "fetch_inflation_prices"),
    ("laboremployment", "fetch_labor_employment"),
    ("moneymarkets", "fetch_money_markets"),
]


@pytest.mark.parametrize("failure", ["ConnectionError", "400"])
@pytest.mark.parametrize("subdir,module", ECONOMY, ids=[e[0] for e in ECONOMY])
def test_economy_collector_main_never_logs_the_fred_key(
    monkeypatch, capsys, caplog, tmp_path, subdir, module, failure
):
    """Run each collector's main() end to end; its handlers print {e} and the traceback."""
    caplog.set_level(logging.DEBUG)
    m = _load(subdir, module)
    calls = []
    monkeypatch.setenv("FRED_API_KEY", KEY)
    monkeypatch.setattr(m.FREDClient, "_rate_limit_wait", lambda self: None)
    monkeypatch.setattr(requests.Session, "get", lambda self, *a, **k: FRED_FAILURES[failure](calls)(*a, **k))
    monkeypatch.setattr(sys, "argv", [module, "--output", str(tmp_path / "out.json")])

    try:
        m.main()
    except SystemExit:
        pass
    except Exception as e:  # a collector without a top-level handler: its uncaught traceback
        import traceback

        traceback.print_exception(e)

    assert calls, "FRED was not called"
    _assert_no_key(capsys, caplog)


# --- the shared helper ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"401 Client Error for url: https://finnhub.io/api/v1/news?category=general&token={KEY}",
        f"https://www.alphavantage.co/query?function=ETF_PROFILE&symbol=SPY&apikey={KEY}",
        f"https://api.stlouisfed.org/fred/series?series_id=X&api_key={KEY}&file_type=json",
        f"params {{'series_id': 'X', 'api_key': '{KEY}', 'file_type': 'json'}}",
        f"url: /x?API_KEY={KEY})",
    ],
)
def test_redact_secrets_strips_key_values(text):
    from shared.redact import redact_secrets

    out = redact_secrets(text)
    assert KEY not in out
    assert "REDACTED" in out


def test_redact_secrets_keeps_other_params():
    from shared.redact import redact_secrets

    out = redact_secrets(f"https://x/q?symbol=SPY&token={KEY}&from=2026-01-01")
    assert out == "https://x/q?symbol=SPY&token=REDACTED&from=2026-01-01"
