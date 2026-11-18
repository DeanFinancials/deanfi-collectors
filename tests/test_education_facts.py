"""
Education-facts collector: fail closed so a bad run never replaces the
last-good education/facts.json, and never leak API keys into CI logs.
Record-level contract checks live in test_facts_contract.py.
"""
import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from educationfacts import run_education_facts
from educationfacts import fetch_group3 as group3
from educationfacts.education_facts_utils import (
    REQUIRED_FIELDS,
    SourceFetchError,
    fetch_with_retry,
    load_config,
    validate_records,
)
from educationfacts.fetch_group1 import fetch_group1, fetch_treasury_rates
from educationfacts.fetch_group2 import _fetch_all_fred, fetch_bls_series, fetch_fred_series


def _mock_http_response(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    return m


def _valid_record(**overrides):
    base = {
        "id": "test-fact",
        "category": "market-education",
        "claim": "Test claim",
        "value": 5.0,
        "unit": "%",
        "source_name": "Test Source",
        "source_url": "https://example.com",
        "as_of": "2026-01-01",
        "max_age_days": 45,
    }
    base.update(overrides)
    return base


def _assert_complete(records):
    assert records
    for rec in records:
        missing = [f for f in REQUIRED_FIELDS if rec.get(f) is None]
        assert not missing, f"{rec.get('id')} missing {missing}"


def _bls_payload(*series):
    return {"Results": {"series": [
        {"seriesID": sid, "data": [{"year": "2026", "period": "M05", "periodName": "May", "value": value}]}
        for sid, value in series
    ]}}


# ── fetch_with_retry ─────────────────────────────────────────────────────────

class TestFetchWithRetry:
    @pytest.mark.parametrize("outcome", [
        {"return_value": _mock_http_response(503)},
        {"side_effect": requests.ConnectionError("unreachable")},
    ], ids=["http-503", "transport-error"])
    def test_exhausted_retries_return_none(self, outcome):
        with patch("educationfacts.education_facts_utils.requests.get", **outcome) as mock_get, \
             patch("educationfacts.education_facts_utils.time.sleep"):
            result = fetch_with_retry("https://api.example.com", max_retries=3, base_delay=0.0)

        assert result is None
        assert mock_get.call_count == 3

    def test_returns_parsed_json_on_200(self):
        resp = _mock_http_response(200, {"data": [{"value": "3.9"}]})
        with patch("educationfacts.education_facts_utils.requests.get", return_value=resp):
            assert fetch_with_retry("https://api.example.com") == {"data": [{"value": "3.9"}]}

    def test_failure_log_has_status_code_but_not_query_param_key(self, caplog):
        secret = "SUPERSECRET_FRED_KEY"
        with patch("educationfacts.education_facts_utils.requests.get",
                   return_value=_mock_http_response(503)), \
             patch("educationfacts.education_facts_utils.time.sleep"), \
             caplog.at_level(logging.INFO, logger="educationfacts.education_facts_utils"):
            fetch_with_retry("https://api.example.com", params={"api_key": secret},
                             max_retries=2, base_delay=0.0)

        assert "503" in caplog.text
        assert secret not in caplog.text


# ── validate_records: bounds ────────────────────────────────────────────────

def test_out_of_bounds_value_is_rejected_and_logged_without_dropping_siblings(caplog):
    valid = _valid_record(id="ok", value=5.0)
    oob = _valid_record(id="rate-fact", value=0.0001)

    with caplog.at_level(logging.WARNING, logger="educationfacts.education_facts_utils"):
        accepted, rejected = validate_records([valid, oob], sane_bounds={"rate-fact": (1.0, 100.0)})

    assert [r["id"] for r in accepted] == ["ok"]
    assert [r["id"] for r in rejected] == ["rate-fact"]
    assert "rate-fact" in caplog.text and "0.0001" in caplog.text


# ── Group 3 seed facts (config.yml) ──────────────────────────────────────────

def test_configured_seed_facts_load_and_pass_validation():
    """A malformed seed edit in config.yml fails the weekly job; catch it at PR time.

    "Today" is pinned to the newest seed as_of date so the check depends only on
    config.yml, not the wall clock. Expiry against the real date is the weekly
    job's concern, not a reason to fail unrelated PRs.
    """
    import datetime

    config = load_config()
    as_of_dates = []
    for raw in config.get("seed_facts", []):
        try:
            as_of_dates.append(datetime.date.fromisoformat(str(raw.get("as_of"))))
        except ValueError:
            pass
    assert as_of_dates, "no parseable seed as_of dates in config.yml"
    pinned_today = max(as_of_dates)

    class PinnedDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(pinned_today.year, pinned_today.month, pinned_today.day)

    with patch("educationfacts.fetch_group3.date", PinnedDate):
        seeds = group3.load_seed_facts(config)

    accepted, rejected = validate_records(seeds, config.get("sane_bounds", {}))

    assert seeds
    assert [r.get("id") for r in rejected] == []
    assert len(accepted) == len(seeds)


class TestSeedStaleness:
    @pytest.fixture(autouse=True)
    def _fixed_today(self):
        import datetime

        class FixedDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 6, 20)

        with patch("educationfacts.fetch_group3.date", FixedDate):
            yield

    def _seed(self, **overrides):
        fields = {"id": "irs-hsa-individual-limit", "value": 4400, "unit": "USD",
                  "as_of": "2025-05-15", "max_age_days": 400, **overrides}
        return {"seed_facts": [_valid_record(**fields)]}

    def test_current_tax_year_seed_outlives_source_age_budget(self):
        assert len(group3.load_seed_facts(self._seed(tax_year=2026))) == 1

    @pytest.mark.parametrize("overrides", [
        {"tax_year": 2025},
        {},
        {"as_of": "not-a-date"},
    ], ids=["prior-tax-year", "no-tax-year", "unparseable-as-of"])
    def test_stale_or_undated_seed_fails_the_group(self, overrides):
        with pytest.raises(SourceFetchError):
            group3.load_seed_facts(self._seed(**overrides))


# ── Group 1 (Treasury, best-effort) ──────────────────────────────────────────

class TestGroup1Treasury:
    def test_treasury_records_are_complete(self):
        treasury_data = {"data": [
            {"record_date": "2026-06-01", "security_desc": "Treasury Notes", "avg_interest_rate_amt": "4.250"},
            {"record_date": "2026-06-01", "security_desc": "Treasury Bonds", "avg_interest_rate_amt": "4.450"},
        ]}
        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=treasury_data):
            _assert_complete(fetch_treasury_rates())

    def test_treasury_outage_raises_but_group1_is_best_effort(self):
        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=None):
            with pytest.raises(SourceFetchError):
                fetch_treasury_rates()
            assert fetch_group1(load_config()) == []


# ── Group 2 (BLS + FRED, required) ───────────────────────────────────────────

FRED_KWARGS = dict(
    series_id="FEDFUNDS", api_key="dummy", fact_id="fred-fed-funds-rate",
    category="market-education", claim="Federal funds effective rate", unit="%",
    source_name="Federal Reserve", source_url="https://www.federalreserve.gov/releases/h15/",
    max_age_days=45,
)


class TestGroup2:
    def test_bls_records_are_complete(self):
        with patch("educationfacts.fetch_group2.requests.post",
                   return_value=_mock_http_response(200, _bls_payload(("LNS14000000", "3.9")))):
            _assert_complete(fetch_bls_series(["LNS14000000"], api_key="FAKE_KEY_NOT_REAL"))

    def test_bls_401_logs_status_code_not_api_key(self, caplog):
        secret_key = "SUPERSECRET_API_KEY_VALUE_XYZ"
        with patch("educationfacts.fetch_group2.requests.post", return_value=_mock_http_response(401)), \
             caplog.at_level(logging.WARNING, logger="educationfacts.fetch_group2"):
            try:
                fetch_bls_series(["LNS14000000"], api_key=secret_key)
            except SourceFetchError:
                pass

        assert "401" in caplog.text
        assert secret_key not in caplog.text

    def test_bls_exhausted_retries_raise(self):
        with patch("educationfacts.fetch_group2.requests.post", return_value=_mock_http_response(503)):
            with pytest.raises(SourceFetchError):
                fetch_bls_series(["LNS14000000"], api_key="key", max_retries=3, base_delay=0.0)

    def test_fred_record_is_complete(self):
        payload = {"observations": [{"date": "2026-05-01", "value": "5.33"}]}
        with patch("educationfacts.fetch_group2.fetch_with_retry", return_value=payload):
            _assert_complete([fetch_fred_series(**FRED_KWARGS)])

    def test_fred_exhausted_retries_raise(self):
        with patch("educationfacts.fetch_group2.fetch_with_retry", return_value=None):
            with pytest.raises(SourceFetchError):
                fetch_fred_series(**FRED_KWARGS)

    def test_monthly_period_start_facts_stay_fresh_until_next_release(self):
        """Monthly figures are dated to the 1st of the observed month, so the latest
        value is legitimately >2 months old just before the next release. A shorter
        budget makes the website freshness probe fail on correct data."""
        bls = _bls_payload(("LNS14000000", "4.3"), ("CUUR0000SA0", "335.123"))
        fred = {"observations": [{"date": "2026-05-01", "value": "5.33"}]}
        with patch("educationfacts.fetch_group2.requests.post", return_value=_mock_http_response(200, bls)), \
             patch("educationfacts.fetch_group2.fetch_with_retry", return_value=fred):
            records = fetch_bls_series(["LNS14000000", "CUUR0000SA0"], api_key="k") + _fetch_all_fred("k")

        budgets = {r["id"]: r["max_age_days"] for r in records}
        for fact_id in ("bls-unemployment-rate", "bls-cpi-all-urban-index", "fred-fed-funds-rate"):
            assert budgets[fact_id] >= 62, f"{fact_id} budget {budgets[fact_id]}d is shorter than two months"


# ── run(): last-good preservation ────────────────────────────────────────────

def _run_with(tmp_path, group1=(), group2=(), group3_records=()):
    output_file = tmp_path / "facts.json"
    with patch("educationfacts.run_education_facts.fetch_group1", **group1), \
         patch("educationfacts.run_education_facts.fetch_group2", **group2), \
         patch("educationfacts.run_education_facts.fetch_group3", **group3_records):
        run_education_facts.run(output_path=str(output_file))
    return output_file


class TestRunEducationFacts:
    def test_required_group_failure_keeps_last_good_and_exits_nonzero(self, tmp_path):
        output_file = tmp_path / "facts.json"
        last_good = '[{"id": "preserved-fact"}]'
        output_file.write_text(last_good)

        with pytest.raises(SystemExit) as exc:
            _run_with(tmp_path, group1={"return_value": []},
                      group2={"side_effect": SourceFetchError("FRED API down")},
                      group3_records={"return_value": [_valid_record()]})

        assert exc.value.code == 1
        assert output_file.read_text() == last_good

    def test_writes_only_valid_records_from_all_groups(self, tmp_path):
        invalid = _valid_record(id="invalid-fact", source_url=None)
        output_file = _run_with(
            tmp_path,
            group1={"return_value": [_valid_record(id="group1-fact")]},
            group2={"return_value": [invalid]},
            group3_records={"return_value": [_valid_record(id="group3-fact", category="retirement")]},
        )

        ids = {r["id"] for r in json.loads(output_file.read_text())}
        assert ids == {"group1-fact", "group3-fact"}

    def test_zero_valid_records_exits_nonzero_without_writing(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            _run_with(tmp_path, group1={"return_value": []}, group2={"return_value": []},
                      group3_records={"return_value": [_valid_record(value=None)]})

        assert exc.value.code == 1
        assert not (tmp_path / "facts.json").exists()
