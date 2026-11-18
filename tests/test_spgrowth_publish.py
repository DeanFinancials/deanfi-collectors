"""Regression: spgrowth must not publish structurally-empty junk records.

A ticker with no resolved SEC CIK (e.g. a stale/mismatched S&P 500 constituent
such as "ECHO", which is in Wikipedia's list but has no SEC ticker->CIK entry),
or a ticker whose SEC fetch returned nothing, produces a CompanyData whose
`growth.ttm` is None and serialises to `"ttm": null`. Downstream dashboards
dereference `growth.ttm.*`, so a single null-ttm row blanks the page.

These records must never reach the published JSON.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("secedgar")  # heavy transitive dep; present in CI

from pathlib import Path  # noqa: E402

from spgrowth.fetch_sp_growth import (  # noqa: E402
    AnnualRecord,
    CompanyData,
    Config,
    GrowthMetrics,
    TTMMetrics,
    is_publishable_company,
    save_growth_output,
)


def _good_company(ticker: str = "AAA") -> CompanyData:
    return CompanyData(
        ticker=ticker,
        cik="0000000001",
        company_name="Alpha Inc.",
        extracted_at="2026-07-01T00:00:00Z",
        annual_data=[
            AnnualRecord(fiscal_year_end="2025-12-31", revenue=1000.0, eps_diluted=2.0)
        ],
        quarterly_data=[],
        growth=GrowthMetrics(
            {"2025": 0.1},
            {"2025": 0.2},
            ttm=TTMMetrics(revenue=1000.0, revenue_yoy=0.1, eps_yoy=0.05),
        ),
        errors=[],
    )


def _cik_not_found(ticker: str = "ECHO") -> CompanyData:
    """Mirrors the fabricated record at fetch_sp_growth.py CIK-not-found branch."""
    return CompanyData(
        ticker=ticker,
        cik="",
        company_name=None,
        extracted_at="2026-07-01T00:00:00Z",
        annual_data=[],
        quarterly_data=[],
        growth=GrowthMetrics({}, {}),
        errors=["CIK not found"],
    )


def _no_sec_data(ticker: str = "NODATA") -> CompanyData:
    """Has a CIK but no usable financials -> also structurally empty (null ttm)."""
    return CompanyData(
        ticker=ticker,
        cik="0000000009",
        company_name=None,
        extracted_at="2026-07-01T00:00:00Z",
        annual_data=[],
        quarterly_data=[],
        growth=GrowthMetrics({}, {}),
        errors=["Failed to fetch SEC data"],
    )


def _minimal_config(output_dir: Path) -> Config:
    return Config(
        user_agent="test",
        years_to_fetch=6,
        quarters_to_fetch=8,
        concepts={},
        output_dir=output_dir,
        indent=2,
        finnhub_enabled=False,
        finnhub_api_key="",
        finnhub_as_reported_enabled=False,
        yfinance_enabled=False,
        alphavantage_enabled=False,
        alphavantage_api_key="",
        fmp_enabled=False,
        fmp_api_key="",
    )


def _partial_company() -> CompanyData:
    # A resolved company with partial errors but real annual data must be kept.
    company = _good_company("PARTIAL")
    company.growth.ttm = None  # e.g. no quarterly data for TTM
    company.errors = ["No annual EPS data found"]
    return company


@pytest.mark.parametrize("company, publishable", [
    (_good_company(), True),
    (_partial_company(), True),
    (_cik_not_found(), False),
    (_no_sec_data(), False),
], ids=["complete", "annual-only", "cik-not-found", "no-sec-data"])
def test_is_publishable_company(company: CompanyData, publishable: bool) -> None:
    assert is_publishable_company(company) is publishable


def test_save_growth_output_drops_structurally_empty_records(tmp_path: Path) -> None:
    results = [_good_company("AAA"), _cik_not_found("ECHO"), _no_sec_data("NODATA")]
    out = tmp_path / "sp500growth.json"

    save_growth_output(results, None, out, "S&P 500", _minimal_config(tmp_path))

    data = json.loads(out.read_text())
    companies = data["companies"]

    assert "AAA" in companies
    assert "ECHO" not in companies, "unresolved-CIK junk record must not be published"
    assert "NODATA" not in companies, "no-SEC-data junk record must not be published"

    # Metadata must reflect only the published set.
    assert data["metadata"]["ticker_count"] == 1

    # Every published record must have a usable (non-null) ttm so dashboards
    # can safely read growth.ttm.*.
    for ticker, company in companies.items():
        assert company["growth"]["ttm"] is not None, f"{ticker} published with null ttm"


# ---------------------------------------------------------------------------
# Website contract: fields deanfi-website reads (src/types/sp500growth.ts,
# src/utils/sp500-growth-data.ts, components/stocks/sp500-index|sp500-growth|
# sector-fundamentals). Keys must exist; numbers are int/float/None.
# ---------------------------------------------------------------------------

_NUM = (int, float, type(None))
COMPANY_KEYS = {
    "ticker", "sector", "cik", "company_name", "extracted_at",
    "annual_values", "quarterly_values", "growth", "errors",
}
GROWTH_KEYS = {
    "revenue_yoy", "eps_yoy", "ttm",
    "revenue_cagr_3yr", "eps_cagr_3yr", "revenue_cagr_5yr", "eps_cagr_5yr",
}
TTM_KEYS = {"revenue", "eps_diluted", "revenue_yoy", "eps_yoy", "as_of_quarter", "source"}


def assert_company_contract(ticker: str, c: dict, *, allow_null_ttm: bool = False) -> None:
    assert set(c) == COMPANY_KEYS, f"{ticker}: keys {sorted(c)}"
    assert c["ticker"] == ticker
    for k in ("ticker", "sector", "cik", "extracted_at"):
        assert isinstance(c[k], str), f"{ticker}.{k}"
    assert isinstance(c["company_name"], (str, type(None)))
    assert isinstance(c["errors"], list) and all(isinstance(e, str) for e in c["errors"])
    for section in ("annual_values", "quarterly_values"):
        assert isinstance(c[section], dict)
        for label, vals in c[section].items():
            assert isinstance(label, str)
            assert set(vals) == {"revenue", "eps"}, f"{ticker}.{section}.{label}"
            assert all(isinstance(v, _NUM) and not isinstance(v, bool) for v in vals.values())
    g = c["growth"]
    assert set(g) == GROWTH_KEYS, f"{ticker}.growth keys {sorted(g)}"
    for k in ("revenue_yoy", "eps_yoy"):
        assert isinstance(g[k], dict) and all(isinstance(v, _NUM) for v in g[k].values())
    for k in ("revenue_cagr_3yr", "eps_cagr_3yr", "revenue_cagr_5yr", "eps_cagr_5yr"):
        assert isinstance(g[k], _NUM), f"{ticker}.growth.{k}"
    if g["ttm"] is None:
        assert allow_null_ttm, f"{ticker}: null ttm"
        return
    assert set(g["ttm"]) == TTM_KEYS, f"{ticker}.growth.ttm keys {sorted(g['ttm'])}"
    for k in ("revenue", "eps_diluted", "revenue_yoy", "eps_yoy"):
        assert isinstance(g["ttm"][k], _NUM)
    assert g["ttm"]["source"] in {"sec", "finnhub", "mixed", "annual_fallback"}


def test_published_file_matches_website_contract(tmp_path: Path) -> None:
    out = tmp_path / "sp100growth.json"
    save_growth_output([_good_company("AAA"), _partial_company()], None, out, "S&P 100", _minimal_config(tmp_path))

    data = json.loads(out.read_text())

    assert {"_README", "metadata", "companies"} <= set(data)
    meta = data["metadata"]
    assert isinstance(meta["generated_at"], str)
    assert isinstance(meta["ticker_count"], int) and isinstance(meta["successful_extractions"], int)
    assert meta["universe"] == "S&P 100"
    for ticker, company in data["companies"].items():
        assert_company_contract(ticker, company, allow_null_ttm=(ticker == "PARTIAL"))
