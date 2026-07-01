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


class TestIsPublishableCompany:
    def test_good_company_is_publishable(self) -> None:
        assert is_publishable_company(_good_company()) is True

    def test_cik_not_found_is_not_publishable(self) -> None:
        assert is_publishable_company(_cik_not_found()) is False

    def test_no_sec_data_is_not_publishable(self) -> None:
        assert is_publishable_company(_no_sec_data()) is False

    def test_cik_with_only_annual_data_is_publishable(self) -> None:
        # A resolved company with partial errors but real data must be kept.
        company = _good_company("PARTIAL")
        company.growth.ttm = None  # e.g. no quarterly data for TTM
        company.errors = ["No annual EPS data found"]
        assert is_publishable_company(company) is True


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
