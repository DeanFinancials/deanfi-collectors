"""
Tests for the education-facts collector (issue 06).

AC1 — required fields non-null per active source
AC2 — 5xx/transport exhaustion: last-good unchanged, exit non-zero
AC3 — sane-bounds/missing-field: reject individual record, keep valid ones, log field+value
AC4 — auth errors log HTTP status code, never credential material
AC5 — A9 prototype: category→source mapping documented; ≥1 record per category present
"""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tracer bullet — fetch_with_retry (AC2 core)
# ---------------------------------------------------------------------------

class TestFetchWithRetry:
    def test_returns_none_after_3_non_2xx_responses(self):
        """Three consecutive 5xx responses → None returned, exactly 3 HTTP calls made."""
        from educationfacts.education_facts_utils import fetch_with_retry

        mock_resp = _mock_http_response(503)
        with patch("educationfacts.education_facts_utils.requests.get", return_value=mock_resp) as mock_get, \
             patch("educationfacts.education_facts_utils.time.sleep"):
            result = fetch_with_retry("https://api.example.com", max_retries=3, base_delay=0.0)

        assert result is None
        assert mock_get.call_count == 3

    def test_returns_none_after_transport_error_on_all_retries(self):
        """Connection error on all 3 retries → None returned."""
        import requests as req_lib
        from educationfacts.education_facts_utils import fetch_with_retry

        with patch("educationfacts.education_facts_utils.requests.get",
                   side_effect=req_lib.ConnectionError("unreachable")) as mock_get, \
             patch("educationfacts.education_facts_utils.time.sleep"):
            result = fetch_with_retry("https://api.example.com", max_retries=3, base_delay=0.0)

        assert result is None
        assert mock_get.call_count == 3

    def test_returns_parsed_json_on_200(self):
        """200 response → parsed JSON dict returned."""
        from educationfacts.education_facts_utils import fetch_with_retry

        mock_resp = _mock_http_response(200, {"data": [{"value": "3.9"}]})
        with patch("educationfacts.education_facts_utils.requests.get", return_value=mock_resp):
            result = fetch_with_retry("https://api.example.com", max_retries=3, base_delay=0.0)

        assert result == {"data": [{"value": "3.9"}]}

    def test_exponential_backoff_sleeps_between_retries(self):
        """Retries use exponential backoff: base_delay, base_delay*2 (not after last attempt)."""
        from educationfacts.education_facts_utils import fetch_with_retry

        mock_resp = _mock_http_response(503)
        with patch("educationfacts.education_facts_utils.requests.get", return_value=mock_resp), \
             patch("educationfacts.education_facts_utils.time.sleep") as mock_sleep:
            fetch_with_retry("https://api.example.com", max_retries=3, base_delay=2.0)

        # 3 attempts → 2 sleeps (no sleep after the last failed attempt)
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0] == call(2.0)
        assert mock_sleep.call_args_list[1] == call(4.0)

    def test_status_code_logged_not_suppressed(self, caplog):
        """Non-2xx status code is visible in logs."""
        from educationfacts.education_facts_utils import fetch_with_retry

        mock_resp = _mock_http_response(503)
        with patch("educationfacts.education_facts_utils.requests.get", return_value=mock_resp), \
             patch("educationfacts.education_facts_utils.time.sleep"), \
             caplog.at_level(logging.WARNING, logger="educationfacts.education_facts_utils"):
            fetch_with_retry("https://api.example.com", max_retries=1, base_delay=0.0)

        assert "503" in " ".join(caplog.messages)

    def test_recovered_transport_error_is_not_logged_as_warning(self, caplog):
        """A transient transport error that succeeds on retry stays below warning level."""
        import requests as req_lib
        from educationfacts.education_facts_utils import fetch_with_retry

        mock_resp = _mock_http_response(200, {"data": []})
        with patch(
            "educationfacts.education_facts_utils.requests.get",
            side_effect=[req_lib.ConnectionError("reset"), mock_resp],
        ), patch("educationfacts.education_facts_utils.time.sleep"), \
             caplog.at_level(logging.WARNING, logger="educationfacts.education_facts_utils"):
            result = fetch_with_retry("https://api.example.com", max_retries=3, base_delay=0.0)

        assert result == {"data": []}
        assert caplog.messages == []


# ---------------------------------------------------------------------------
# Slice 2 — validate_records (AC3)
# ---------------------------------------------------------------------------

class TestValidateRecords:
    def test_rejects_oob_record_keeps_valid_sibling(self):
        """OOB value → rejected; sibling valid record → accepted."""
        from educationfacts.education_facts_utils import validate_records

        valid = _valid_record(id="ok", value=5.0)
        oob = _valid_record(id="bad-bounds", value=0.001)
        bounds = {"bad-bounds": (1.0, 100.0)}

        accepted, rejected = validate_records([valid, oob], sane_bounds=bounds)

        assert len(accepted) == 1 and accepted[0]["id"] == "ok"
        assert len(rejected) == 1 and rejected[0]["id"] == "bad-bounds"

    def test_rejects_record_missing_required_field(self):
        """Record with a missing required field → rejected."""
        from educationfacts.education_facts_utils import validate_records

        bad = _valid_record()
        del bad["source_url"]

        accepted, rejected = validate_records([bad], sane_bounds={})
        assert len(accepted) == 0 and len(rejected) == 1

    def test_rejects_record_with_null_required_field(self):
        """Required field present but None → rejected."""
        from educationfacts.education_facts_utils import validate_records

        bad = _valid_record(value=None)
        accepted, rejected = validate_records([bad], sane_bounds={})
        assert len(accepted) == 0 and len(rejected) == 1

    def test_rejection_log_contains_field_and_observed_value(self, caplog):
        """Rejection log includes the fact id, field name, and observed value."""
        from educationfacts.education_facts_utils import validate_records

        oob = _valid_record(id="rate-fact", value=0.0001)
        with caplog.at_level(logging.WARNING, logger="educationfacts.education_facts_utils"):
            validate_records([oob], sane_bounds={"rate-fact": (1.0, 100.0)})

        combined = " ".join(caplog.messages)
        assert "rate-fact" in combined
        assert "0.0001" in combined

    def test_empty_input_returns_empty_lists(self):
        """Empty input → both lists empty."""
        from educationfacts.education_facts_utils import validate_records
        accepted, rejected = validate_records([], sane_bounds={})
        assert accepted == [] and rejected == []


# ---------------------------------------------------------------------------
# Slice 3 — Group 3 seed facts (AC1, AC5 A9 prototype)
# ---------------------------------------------------------------------------

class TestGroup3SeedFacts:
    def test_all_seed_facts_have_required_fields_non_null(self):
        """Every seed fact in config has all required fields present and non-null."""
        from educationfacts.fetch_group3 import load_seed_facts
        from educationfacts.education_facts_utils import REQUIRED_FIELDS, load_config

        config = load_config()
        seeds = load_seed_facts(config)

        assert len(seeds) >= 1, "At least one seed fact must be defined"
        for rec in seeds:
            for field in REQUIRED_FIELDS:
                assert field in rec and rec[field] is not None, \
                    f"Seed id={rec.get('id', '?')} has missing/null field: {field}"

    def test_seed_facts_cover_retirement_and_financial_tips_categories(self):
        """Seeds must include retirement (IRS) and financial-tips (FSA) facts."""
        from educationfacts.fetch_group3 import load_seed_facts
        from educationfacts.education_facts_utils import load_config

        config = load_config()
        seeds = load_seed_facts(config)
        categories = {r["category"] for r in seeds}

        assert "retirement" in categories, "Must have retirement seeds (IRS/SSA data)"
        assert "financial-tips" in categories, "Must have financial-tips seeds (FSA/IRS data)"

    def test_annual_seed_facts_are_within_400_day_staleness_threshold(self):
        """Every seed fact with max_age_days==400 has as_of within 400 days of today."""
        from datetime import date, datetime
        from educationfacts.fetch_group3 import load_seed_facts
        from educationfacts.education_facts_utils import load_config

        config = load_config()
        seeds = load_seed_facts(config)
        today = date.today()

        for rec in seeds:
            if rec.get("max_age_days") == 400:
                as_of = datetime.strptime(rec["as_of"], "%Y-%m-%d").date()
                age_days = (today - as_of).days
                assert age_days <= 400, \
                    f"Seed id={rec['id']} is {age_days} days old, exceeds max_age_days=400"


# ---------------------------------------------------------------------------
# Slice 4 — Group 1 Treasury fetch (AC1, mocked HTTP)
# ---------------------------------------------------------------------------

class TestGroup1TreasuryFetch:
    def test_treasury_fetch_returns_records_with_all_required_fields(self):
        """Mocked Treasury API → records with all required fields non-null."""
        from educationfacts.fetch_group1 import fetch_treasury_rates
        from educationfacts.education_facts_utils import REQUIRED_FIELDS

        treasury_data = {
            "data": [
                {"record_date": "2026-06-01", "security_desc": "Treasury Notes",
                 "avg_interest_rate_amt": "4.250"},
                {"record_date": "2026-06-01", "security_desc": "Treasury Bonds",
                 "avg_interest_rate_amt": "4.450"},
            ]
        }
        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=treasury_data):
            records = fetch_treasury_rates()

        assert len(records) >= 1
        for rec in records:
            for field in REQUIRED_FIELDS:
                assert field in rec and rec[field] is not None, \
                    f"Treasury record missing field: {field}"

    def test_treasury_rates_raises_source_fetch_error_on_api_failure(self):
        """fetch_treasury_rates raises SourceFetchError on None response."""
        from educationfacts.fetch_group1 import fetch_treasury_rates
        from educationfacts.education_facts_utils import SourceFetchError

        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=None):
            with pytest.raises(SourceFetchError):
                fetch_treasury_rates()

    def test_fetch_group1_returns_empty_list_on_treasury_failure(self):
        """fetch_group1 (best-effort) swallows SourceFetchError and returns [] without raising."""
        from educationfacts.fetch_group1 import fetch_group1
        from educationfacts.education_facts_utils import load_config

        config = load_config()
        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=None):
            result = fetch_group1(config)

        assert result == []

    def test_treasury_fetch_uses_current_fiscal_data_v2_endpoint(self):
        """Treasury fetch uses the live Fiscal Data v2 route and filters security_desc values."""
        from educationfacts.fetch_group1 import fetch_treasury_rates

        treasury_data = {
            "data": [
                {"record_date": "2026-05-31", "security_desc": "Treasury Notes",
                 "avg_interest_rate_amt": "3.248"},
                {"record_date": "2026-05-31", "security_desc": "Treasury Bonds",
                 "avg_interest_rate_amt": "3.413"},
            ]
        }
        with patch("educationfacts.fetch_group1.fetch_with_retry", return_value=treasury_data) as mock_fetch:
            fetch_treasury_rates()

        requested_url = mock_fetch.call_args.args[0]
        assert "/services/api/fiscal_service/v2/accounting/od/avg_interest_rates" in requested_url
        assert "filter=security_desc:in:(Treasury%20Notes,Treasury%20Bonds)" in requested_url


# ---------------------------------------------------------------------------
# Slice 5 — Group 2 BLS fetch + AC4 no-key-in-logs
# ---------------------------------------------------------------------------

class TestGroup2BLSFetch:
    def test_bls_fetch_unemployment_returns_complete_record(self):
        """Mocked BLS 200 response → unemployment fact record with all required fields."""
        from educationfacts.fetch_group2 import fetch_bls_series
        from educationfacts.education_facts_utils import REQUIRED_FIELDS

        bls_payload = {
            "Results": {
                "series": [{
                    "seriesID": "LNS14000000",
                    "data": [{"year": "2026", "period": "M05", "periodName": "May", "value": "3.9"}]
                }]
            }
        }
        with patch("educationfacts.fetch_group2.requests.post",
                   return_value=_mock_http_response(200, bls_payload)):
            records = fetch_bls_series(["LNS14000000"], api_key="FAKE_KEY_NOT_REAL")

        assert len(records) >= 1
        for rec in records:
            for field in REQUIRED_FIELDS:
                assert field in rec and rec[field] is not None

    def test_bls_logs_status_code_not_api_key_on_401(self, caplog):
        """On BLS 401: log contains HTTP status code; api_key value NEVER appears in log."""
        from educationfacts.fetch_group2 import fetch_bls_series

        secret_key = "SUPERSECRET_API_KEY_VALUE_XYZ"
        with patch("educationfacts.fetch_group2.requests.post",
                   return_value=_mock_http_response(401)), \
             caplog.at_level(logging.WARNING, logger="educationfacts.fetch_group2"):
            try:
                fetch_bls_series(["LNS14000000"], api_key=secret_key)
            except Exception:
                pass  # We only care about what's logged

        combined_log = " ".join(caplog.messages)
        assert "401" in combined_log, "HTTP status code must be logged"
        assert secret_key not in combined_log, "API key must NOT appear in logs"

    def test_bls_raises_source_fetch_error_on_exhausted_retries(self):
        """BLS 5xx on all retries → SourceFetchError raised."""
        from educationfacts.fetch_group2 import fetch_bls_series
        from educationfacts.education_facts_utils import SourceFetchError

        with patch("educationfacts.fetch_group2.requests.post",
                   return_value=_mock_http_response(503)):
            with pytest.raises(SourceFetchError):
                fetch_bls_series(["LNS14000000"], api_key="key", max_retries=3, base_delay=0.0)

    def test_bls_monthly_facts_use_release_calendar_aware_freshness_windows(self):
        """BLS monthly facts use period-start as_of, so budgets must cover publication lag."""
        from educationfacts.fetch_group2 import fetch_bls_series

        bls_payload = {
            "Results": {
                "series": [
                    {
                        "seriesID": "LNS14000000",
                        "data": [{"year": "2026", "period": "M05", "periodName": "May", "value": "4.3"}],
                    },
                    {
                        "seriesID": "CUUR0000SA0",
                        "data": [{"year": "2026", "period": "M05", "periodName": "May", "value": "335.123"}],
                    },
                ]
            }
        }
        with patch("educationfacts.fetch_group2.requests.post",
                   return_value=_mock_http_response(200, bls_payload)):
            records = fetch_bls_series(["LNS14000000", "CUUR0000SA0"], api_key="FAKE_KEY_NOT_REAL")

        by_id = {record["id"]: record for record in records}
        assert by_id["bls-unemployment-rate"]["max_age_days"] == 70
        assert by_id["bls-cpi-all-urban-index"]["max_age_days"] == 80


# ---------------------------------------------------------------------------
# Slice 6 — Group 2 FRED fetch (AC1, mocked)
# ---------------------------------------------------------------------------

class TestGroup2FREDFetch:
    def test_fred_fetch_returns_record_with_required_fields(self):
        """Mocked FRED 200 response → fact record with all required fields non-null."""
        from educationfacts.fetch_group2 import fetch_fred_series
        from educationfacts.education_facts_utils import REQUIRED_FIELDS

        fred_payload = {"observations": [{"date": "2026-05-01", "value": "5.33"}]}
        with patch("educationfacts.fetch_group2.fetch_with_retry", return_value=fred_payload):
            record = fetch_fred_series(
                series_id="FEDFUNDS",
                api_key="dummy",
                fact_id="fred-fed-funds-rate",
                category="market-education",
                claim="Federal funds effective rate",
                unit="%",
                source_name="Federal Reserve",
                source_url="https://www.federalreserve.gov/releases/h15/",
                max_age_days=45,
            )

        assert record is not None
        for field in REQUIRED_FIELDS:
            assert field in record and record[field] is not None

    def test_fred_fetch_raises_source_fetch_error_on_none(self):
        """fetch_with_retry returns None (exhausted) → SourceFetchError raised."""
        from educationfacts.fetch_group2 import fetch_fred_series
        from educationfacts.education_facts_utils import SourceFetchError

        with patch("educationfacts.fetch_group2.fetch_with_retry", return_value=None):
            with pytest.raises(SourceFetchError):
                fetch_fred_series(
                    series_id="FEDFUNDS", api_key="key",
                    fact_id="fred-fed-funds-rate", category="market-education",
                    claim="Fed funds rate", unit="%",
                    source_name="Federal Reserve",
                    source_url="https://www.federalreserve.gov/releases/h15/",
                    max_age_days=45,
                )

    def test_fed_funds_monthly_average_uses_period_start_aware_freshness_window(self):
        """FEDFUNDS is a monthly average with first-of-month observations."""
        from educationfacts.fetch_group2 import _FRED_SERIES

        fed_funds = next(series for series in _FRED_SERIES if series["series_id"] == "FEDFUNDS")
        assert fed_funds["max_age_days"] == 70


# ---------------------------------------------------------------------------
# Slice 7 — run_education_facts integration (AC2 full: keeps last-good)
# ---------------------------------------------------------------------------

class TestRunEducationFacts:
    def test_keeps_lastgood_and_exits_nonzero_when_group2_raises(self, tmp_path):
        """SourceFetchError from Group 2 (required) → output file unchanged, sys.exit(1)."""
        from educationfacts import run_education_facts
        from educationfacts.education_facts_utils import SourceFetchError

        output_file = tmp_path / "facts.json"
        last_good_content = '[{"id": "preserved-fact"}]'
        output_file.write_text(last_good_content)

        with patch("educationfacts.run_education_facts.fetch_group1", return_value=[]), \
             patch("educationfacts.run_education_facts.fetch_group2",
                   side_effect=SourceFetchError("FRED API down")), \
             patch("educationfacts.run_education_facts.fetch_group3", return_value=[_valid_record()]):
            with pytest.raises(SystemExit) as exc:
                run_education_facts.run(output_path=str(output_file))

        assert exc.value.code == 1
        assert output_file.read_text() == last_good_content

    def test_writes_output_when_all_groups_succeed(self, tmp_path):
        """All groups succeed → facts.json written with merged records."""
        from educationfacts import run_education_facts

        output_file = tmp_path / "facts.json"
        r1 = _valid_record(id="group1-fact", category="market-education")
        r2 = _valid_record(id="group3-fact", category="retirement")

        with patch("educationfacts.run_education_facts.fetch_group1", return_value=[r1]), \
             patch("educationfacts.run_education_facts.fetch_group2", return_value=[]), \
             patch("educationfacts.run_education_facts.fetch_group3", return_value=[r2]):
            run_education_facts.run(output_path=str(output_file))

        written = json.loads(output_file.read_text())
        ids = {r["id"] for r in written}
        assert "group1-fact" in ids
        assert "group3-fact" in ids

    def test_exits_nonzero_when_all_groups_produce_zero_valid_records(self, tmp_path):
        """Zero valid records after validation → sys.exit(1)."""
        from educationfacts import run_education_facts

        output_file = tmp_path / "facts.json"
        with patch("educationfacts.run_education_facts.fetch_group1", return_value=[]), \
             patch("educationfacts.run_education_facts.fetch_group2", return_value=[]), \
             patch("educationfacts.run_education_facts.fetch_group3", return_value=[]):
            with pytest.raises(SystemExit) as exc:
                run_education_facts.run(output_path=str(output_file))

        assert exc.value.code == 1
        assert not output_file.exists()
