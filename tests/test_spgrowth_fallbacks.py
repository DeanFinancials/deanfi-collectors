"""Regression: partial Alpha Vantage / FMP responses must never abort a spgrowth run.

Alpha Vantage rate-limits by returning HTTP 200 with a {"Note": ...} or
{"Information": ...} body. When INCOME_STATEMENT was limited but EARNINGS
returned data, ``alphavantage_annual_financials`` built a DataFrame with no
``revenue`` column and raised KeyError: 'revenue', which nothing caught.

Every test mocks ``requests.get``; no network.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

pytest.importorskip("secedgar")  # heavy transitive dep; present in CI

from spgrowth import fetch_sp_growth as sg  # noqa: E402

COLUMNS = ["end", "revenue", "eps_diluted", "source"]

AV_NOTE = {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute."}
AV_INFO = {"Information": "We have detected your API key and our standard API rate limit is 25 requests per day."}

AV_INCOME = {
    "symbol": "AAA",
    "annualReports": [
        {"fiscalDateEnding": "2025-12-31", "totalRevenue": "1000"},
        {"fiscalDateEnding": "2024-12-31", "totalRevenue": "900"},
    ],
}
AV_EARNINGS = {
    "symbol": "AAA",
    "annualEarnings": [
        {"fiscalDateEnding": "2026-09-30", "reportedEPS": "2.6"},  # TTM-ish, no revenue
        {"fiscalDateEnding": "2025-12-31", "reportedEPS": "2.5"},
        {"fiscalDateEnding": "2024-12-31", "reportedEPS": "2.0"},
    ],
}


class _Resp:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _mock_get(monkeypatch, *, income=None, earnings=None, fmp=None):
    """Route requests.get by provider/function. Each value is a _Resp or Exception."""
    calls = []

    def fake_get(url, params=None, timeout=None, **kwargs):
        params = params or {}
        calls.append((url, dict(params)))
        if "alphavantage" in url:
            fn = params.get("function") or ("INCOME_STATEMENT" if "INCOME_STATEMENT" in url else "EARNINGS")
            target = income if fn == "INCOME_STATEMENT" else earnings
        elif "financialmodelingprep" in url:
            target = fmp
        else:  # pragma: no cover - any other host is a test bug
            raise AssertionError(f"unexpected URL {url}")
        if isinstance(target, Exception):
            raise target
        return target if target is not None else _Resp(200, {})

    monkeypatch.setattr(sg.requests, "get", fake_get)
    return calls


def _assert_frame(df: pd.DataFrame) -> None:
    assert isinstance(df, pd.DataFrame)
    assert set(COLUMNS) <= set(df.columns), f"missing columns: {set(COLUMNS) - set(df.columns)}"


# --------------------------------------------------------------------------
# Alpha Vantage: each call fails independently
# --------------------------------------------------------------------------

@pytest.mark.parametrize("income_body", [AV_NOTE, AV_INFO, {}, {"annualReports": []}, {"annualReports": None}],
                         ids=["note", "information", "empty", "empty-list", "null-list"])
def test_av_income_limited_earnings_ok_returns_no_rows(monkeypatch, income_body):
    """The production crash: INCOME_STATEMENT limited, EARNINGS has data."""
    _mock_get(monkeypatch, income=_Resp(200, income_body), earnings=_Resp(200, AV_EARNINGS))

    df = sg.alphavantage_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df.empty  # EPS-only rows are dropped by the revenue filter, as before


@pytest.mark.parametrize("earnings_body", [AV_NOTE, AV_INFO, {}, "not a dict"],
                         ids=["note", "information", "empty", "string"])
def test_av_income_ok_earnings_limited_keeps_revenue(monkeypatch, earnings_body):
    _mock_get(monkeypatch, income=_Resp(200, AV_INCOME), earnings=_Resp(200, earnings_body))

    df = sg.alphavantage_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df["end"].tolist() == ["2025-12-31", "2024-12-31"]
    assert df["revenue"].tolist() == [1000.0, 900.0]
    assert df["eps_diluted"].isna().all()


@pytest.mark.parametrize("failure", [
    _Resp(200, AV_NOTE),
    _Resp(503, "Service Unavailable"),
    _Resp(200, ValueError("Expecting value")),  # non-JSON body
    ConnectionError("boom"),
], ids=["note", "http-503", "non-json", "network"])
def test_av_both_calls_fail_returns_empty(monkeypatch, failure):
    _mock_get(monkeypatch, income=failure, earnings=failure)

    df = sg.alphavantage_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df.empty


def test_av_missing_keys_and_none_strings_degrade_to_partial(monkeypatch):
    income = {"annualReports": [
        {"fiscalDateEnding": "2025-12-31", "totalRevenue": "None"},
        {"fiscalDateEnding": "2024-12-31", "totalRevenue": "900"},
        {"fiscalDateEnding": "2023-12-31"},  # no totalRevenue key
        {"totalRevenue": "800"},  # no date
        "garbage-row",
        {"fiscalDateEnding": "2022-12-31", "totalRevenue": "NaN"},
        {"fiscalDateEnding": "2021-12-31", "totalRevenue": "Infinity"},
    ]}
    earnings = {"annualEarnings": [
        {"fiscalDateEnding": "2024-12-31", "reportedEPS": "None"},
        {"fiscalDateEnding": "2025-12-31"},
    ]}
    _mock_get(monkeypatch, income=_Resp(200, income), earnings=_Resp(200, earnings))

    df = sg.alphavantage_annual_financials("AAA", "key", years_to_fetch=10)

    _assert_frame(df)
    assert df["end"].tolist() == ["2024-12-31"]
    assert df["revenue"].tolist() == [900.0]
    assert df["eps_diluted"].isna().all()


def test_av_full_response_unchanged(monkeypatch):
    _mock_get(monkeypatch, income=_Resp(200, AV_INCOME), earnings=_Resp(200, AV_EARNINGS))

    df = sg.alphavantage_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df[COLUMNS].to_dict("records") == [
        {"end": "2025-12-31", "revenue": 1000.0, "eps_diluted": 2.5, "source": "alphavantage"},
        {"end": "2024-12-31", "revenue": 900.0, "eps_diluted": 2.0, "source": "alphavantage"},
    ]


# --------------------------------------------------------------------------
# FMP
# --------------------------------------------------------------------------

FMP_OK = [
    {"date": "2025-12-31", "period": "FY", "revenue": 1000, "epsDiluted": 2.5},
    {"date": "2024-12-31", "period": "FY", "revenue": 900, "epsDiluted": 2.0},
]


@pytest.mark.parametrize("resp", [
    _Resp(429, {"Error Message": "Limit Reach . Please upgrade your plan"}),
    _Resp(402, {"Error Message": "Premium Query Parameter"}),
    _Resp(200, {"Error Message": "Limit Reach . Please upgrade your plan"}),  # 200 + dict body
    _Resp(200, []),
    _Resp(200, None),
    _Resp(200, ValueError("Expecting value")),
    _Resp(500, ValueError("Expecting value")),
    ConnectionError("boom"),
], ids=["429", "402", "200-error-dict", "200-empty", "200-null", "non-json", "500", "network"])
def test_fmp_error_bodies_return_empty(monkeypatch, resp):
    _mock_get(monkeypatch, fmp=resp)

    df = sg.fmp_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df.empty


def test_fmp_missing_fields_keep_columns(monkeypatch):
    body = [
        {"date": "2025-12-31", "period": "FY", "epsDiluted": 2.5},  # no revenue
        {"date": "2024-12-31", "period": "FY", "revenue": None, "epsDiluted": "None"},
        {"date": "2023-12-31", "period": "Q4", "revenue": 1, "epsDiluted": 1},  # not FY
        {"period": "FY", "revenue": 1},  # no date
        "garbage-row",
    ]
    _mock_get(monkeypatch, fmp=_Resp(200, body))

    df = sg.fmp_annual_financials("AAA", "key")

    _assert_frame(df)
    assert df["end"].tolist() == ["2025-12-31", "2024-12-31"]
    assert df["revenue"].isna().all()
    assert df["eps_diluted"].tolist()[0] == 2.5
    # Downstream lookup must not raise on the all-NaN revenue column.
    assert sg.get_fallback_value("2025-12-31", {"fmp": df}, "revenue").value is None
    assert sg.get_fallback_value("2025-12-31", {"fmp": df}, "eps_diluted").value == 2.5


def test_fmp_full_response_unchanged(monkeypatch):
    _mock_get(monkeypatch, fmp=_Resp(200, FMP_OK))

    df = sg.fmp_annual_financials("AAA", "key")

    assert df[COLUMNS].to_dict("records") == [
        {"end": "2025-12-31", "revenue": 1000.0, "eps_diluted": 2.5, "source": "fmp"},
        {"end": "2024-12-31", "revenue": 900.0, "eps_diluted": 2.0, "source": "fmp"},
    ]


def test_api_keys_go_in_params_not_logged(monkeypatch, capsys):
    calls = _mock_get(monkeypatch, income=ConnectionError("https://x/?apikey=SECRET"),
                      earnings=_Resp(200, AV_NOTE), fmp=ConnectionError("https://x/?apikey=SECRET"))

    sg.alphavantage_annual_financials("AAA", "SECRET")
    sg.fmp_annual_financials("AAA", "SECRET")

    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    assert all("SECRET" not in url for url, _ in calls)


# --------------------------------------------------------------------------
# End to end through extract_company_data: run continues, record shape intact
# --------------------------------------------------------------------------

def _config(**overrides) -> sg.Config:
    base = dict(
        user_agent="test",
        years_to_fetch=6,
        quarters_to_fetch=8,
        concepts={},
        output_dir=None,
        indent=2,
        finnhub_enabled=False,
        finnhub_api_key="",
        finnhub_as_reported_enabled=False,
        yfinance_enabled=False,
        alphavantage_enabled=True,
        alphavantage_api_key="key",
        fmp_enabled=True,
        fmp_api_key="key",
    )
    base.update(overrides)
    return sg.Config(**base)


@pytest.mark.parametrize("income, earnings, fmp", [
    (_Resp(200, AV_NOTE), _Resp(200, AV_EARNINGS), _Resp(429, {"Error Message": "Limit"})),
    (_Resp(200, AV_INFO), _Resp(200, AV_EARNINGS), _Resp(200, {"Error Message": "Limit"})),
    (_Resp(200, AV_NOTE), _Resp(200, AV_NOTE), _Resp(402, {})),
], ids=["av-mixed+fmp-429", "av-mixed+fmp-200-error", "all-limited"])
def test_extract_company_data_survives_limited_fallbacks(monkeypatch, income, earnings, fmp):
    _mock_get(monkeypatch, income=income, earnings=earnings, fmp=fmp)

    data = sg.extract_company_data("AAA", "0000000001", {"entityName": "Alpha Inc.", "facts": {}}, _config())

    assert data.annual_data == []  # no source had revenue/EPS by year -> nothing invented
    assert sg.is_publishable_company(data) is False  # and the empty record is not published


def test_extract_company_data_fallback_record_shape(monkeypatch):
    """When fallbacks do return data, the published record keeps the website's shape."""
    from tests.test_spgrowth_publish import assert_company_contract

    _mock_get(monkeypatch, income=_Resp(200, AV_INCOME), earnings=_Resp(200, AV_NOTE), fmp=_Resp(200, FMP_OK))

    data = sg.extract_company_data("AAA", "0000000001", {"entityName": "Alpha Inc.", "facts": {}}, _config())

    assert [a.fiscal_year_end for a in data.annual_data] == ["2025-12-31", "2024-12-31"]
    # revenue comes from AV (priority), cross-checked with FMP; EPS from FMP only.
    assert data.annual_data[0].revenue == 1000.0
    assert data.annual_data[0].revenue_validation == "validated"
    assert data.annual_data[0].eps_diluted == 2.5
    assert data.annual_data[0].eps_validation == "single_source"

    record = json.loads(json.dumps(sg.company_data_to_dict(data)))
    assert_company_contract("AAA", record, allow_null_ttm=True)
    assert record["annual_values"] == {"2025": {"revenue": 1000.0, "eps": 2.5},
                                       "2024": {"revenue": 900.0, "eps": 2.0}}
    assert record["growth"]["revenue_yoy"] == {"2025": round(1000 / 900 - 1, 4)}
    for v in record["annual_values"].values():
        assert all(type(x) in (int, float) for x in v.values())
