"""
Tests for the GSC topics collector (Issue 08 — C2a).

TDD vertical slices:
  TestAuthenticateGSC       — authentication behaviors (AC1/AC4)
  TestFetchSearchAnalytics  — Search Analytics call behaviors (AC2/AC4/NFR-3)
  TestFetchGSCTopics        — integration: auth + fetch + filter + seed merge
  TestOpportunityScore      — utility function
  TestValidateTopics        — schema validation (AC3)
  TestRunGSCTopics          — run() entry-point behaviors (AC4 last-good + AC1)
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from gsctopics.fetch_gsc import (
    authenticate_gsc,
    fetch_gsc_topics,
    fetch_search_analytics,
    load_seed_topics,
)
from gsctopics.gsc_topics_utils import (
    SourceFetchError,
    assign_category,
    is_quality_query,
    opportunity_score,
    slugify,
    validate_topics,
)
from gsctopics.run_gsc_topics import run


# ── helpers ──────────────────────────────────────────────────────────────────

def _gsc_env(monkeypatch):
    monkeypatch.setenv("GSC_CLIENT_ID", "test_id")
    monkeypatch.setenv("GSC_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("GSC_REFRESH_TOKEN", "test_refresh")


def _gsc_row(query, page, impressions=100.0, clicks=0.0, position=5.0):
    return {
        "keys": [query, page],
        "impressions": impressions,
        "clicks": clicks,
        "ctr": clicks / impressions if impressions else 0.0,
        "position": position,
    }


def _gsc_response(rows):
    return {"rows": rows}


def _valid_topic():
    return {
        "slug": "roth-ira-limits",
        "category": "retirement",
        "target_keyword": "roth ira limits",
        "added_at": "2026-06-10",
        "status": "suggested",
        "source": "gsc",
        "gsc_evidence": {
            "impressions": 100.0,
            "avg_position": 5.0,
            "clicks": 2.0,
            "window": "90d",
        },
        "title_working": "Roth Ira Limits",
        "secondary_keywords": [],
        "internal_link_targets": [],
        "facts_refs": [],
        "vertical": None,
    }


# ── TestAuthenticateGSC ───────────────────────────────────────────────────────

class TestAuthenticateGSC:
    @patch("gsctopics.fetch_gsc.GoogleRequest")
    @patch("gsctopics.fetch_gsc.Credentials")
    def test_returns_access_token_when_credentials_present(
        self, mock_creds_cls, _mock_req_cls, monkeypatch
    ):
        _gsc_env(monkeypatch)
        mock_creds = MagicMock()
        mock_creds.token = "my_access_token"
        mock_creds_cls.return_value = mock_creds

        token = authenticate_gsc()

        assert token == "my_access_token"
        mock_creds.refresh.assert_called_once()

    def test_raises_when_all_env_vars_missing(self, monkeypatch):
        monkeypatch.delenv("GSC_CLIENT_ID", raising=False)
        monkeypatch.delenv("GSC_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("GSC_REFRESH_TOKEN", raising=False)

        with pytest.raises(SourceFetchError, match="GSC credentials not set"):
            authenticate_gsc()

    def test_raises_when_one_env_var_missing(self, monkeypatch):
        monkeypatch.setenv("GSC_CLIENT_ID", "id")
        monkeypatch.setenv("GSC_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GSC_REFRESH_TOKEN", raising=False)

        with pytest.raises(SourceFetchError, match="GSC_REFRESH_TOKEN"):
            authenticate_gsc()

    @patch("gsctopics.fetch_gsc.GoogleRequest")
    @patch("gsctopics.fetch_gsc.Credentials")
    def test_raises_on_invalid_grant_refresh_error(
        self, mock_creds_cls, _mock_req_cls, monkeypatch
    ):
        _gsc_env(monkeypatch)
        from google.auth.exceptions import RefreshError
        mock_creds = MagicMock()
        mock_creds.refresh.side_effect = RefreshError("invalid_grant")
        mock_creds_cls.return_value = mock_creds

        with pytest.raises(SourceFetchError, match="token refresh failed"):
            authenticate_gsc()


# ── TestFetchSearchAnalytics ──────────────────────────────────────────────────

class TestFetchSearchAnalytics:
    @patch("gsctopics.fetch_gsc.requests.post")
    def test_excludes_insights_pages(self, mock_post):
        rows = [
            _gsc_row("roth ira guide", "https://deanfi.com/insights/roth-ira/", impressions=200),
            _gsc_row("retirement planning basics", "https://deanfi.com/retirement/", impressions=150),
        ]
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: _gsc_response(rows)
        )

        results = fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, ["/insights/"])

        assert len(results) == 1
        assert results[0]["target_keyword"] == "retirement planning basics"

    @patch("gsctopics.fetch_gsc.requests.post")
    def test_required_schema_fields_present_on_success(self, mock_post):
        rows = [_gsc_row("401k contribution limits", "https://deanfi.com/retirement/")]
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: _gsc_response(rows)
        )

        results = fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, [])

        assert len(results) == 1
        e = results[0]
        for field in ("slug", "category", "target_keyword", "gsc_evidence", "added_at", "status"):
            assert field in e, f"missing field: {field}"
        for sub in ("impressions", "avg_position", "clicks", "window"):
            assert sub in e["gsc_evidence"], f"gsc_evidence missing: {sub}"
        assert e["status"] == "suggested"
        assert e["source"] == "gsc"
        assert e["gsc_evidence"]["window"] == "90d"

    @patch("gsctopics.fetch_gsc.requests.post")
    def test_empty_rows_returns_empty_list(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {}  # no "rows" key
        )

        results = fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, [])

        assert results == []

    @patch("gsctopics.fetch_gsc.requests.post")
    def test_raises_source_fetch_error_on_401(self, mock_post):
        mock_post.return_value = MagicMock(status_code=401)

        with pytest.raises(SourceFetchError, match="HTTP 401"):
            fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, [])

    @patch("gsctopics.fetch_gsc.time.sleep", return_value=None)
    @patch("gsctopics.fetch_gsc.requests.post")
    def test_401_logs_status_code_not_token_value(self, mock_post, _mock_sleep, caplog):
        mock_post.return_value = MagicMock(status_code=401)
        secret_token = "super_secret_access_token_value"

        import logging
        with caplog.at_level(logging.WARNING, logger="gsctopics.fetch_gsc"):
            with pytest.raises(SourceFetchError):
                fetch_search_analytics(secret_token, "sc-domain:deanfi.com", 90, [])

        assert secret_token not in caplog.text
        assert "401" in caplog.text

    @patch("gsctopics.fetch_gsc.time.sleep", return_value=None)
    @patch("gsctopics.fetch_gsc.requests.post")
    def test_raises_after_all_retries_on_5xx(self, mock_post, _mock_sleep):
        mock_post.return_value = MagicMock(status_code=503)

        with pytest.raises(SourceFetchError, match="failed after all retries"):
            fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, [], max_retries=3)

        assert mock_post.call_count == 3


# ── TestFetchGSCTopics ────────────────────────────────────────────────────────

class TestFetchGSCTopics:
    def _config(self, seeds=None):
        return {
            "site_url": "sc-domain:deanfi.com",
            "window_days": 90,
            "max_topics": 50,
            "min_impressions": 5,
            "excluded_page_prefixes": ["/insights/"],
            "seed_topics": seeds or [],
        }

    @patch("gsctopics.fetch_gsc.fetch_search_analytics")
    @patch("gsctopics.fetch_gsc.authenticate_gsc", return_value="tok")
    def test_seed_topics_appended_to_output(self, _mock_auth, mock_fetch):
        mock_fetch.return_value = []
        seed = {
            "slug": "how-to-invest",
            "category": "market-education",
            "target_keyword": "how to invest",
            "source": "wes",
            "status": "suggested",
            "added_at": "2026-06-10",
        }

        result = fetch_gsc_topics(self._config(seeds=[seed]))

        assert len(result) == 1
        assert result[0]["slug"] == "how-to-invest"
        assert result[0]["source"] == "wes"

    @patch("gsctopics.fetch_gsc.fetch_search_analytics")
    @patch("gsctopics.fetch_gsc.authenticate_gsc", return_value="tok")
    def test_gsc_wins_over_seed_on_slug_collision(self, _mock_auth, mock_fetch):
        gsc_entry = dict(_valid_topic(), slug="retirement-basics", source="gsc")
        mock_fetch.return_value = [gsc_entry]
        seed = {"slug": "retirement-basics", "source": "wes", "status": "suggested", "added_at": "2026-06-10"}

        result = fetch_gsc_topics(self._config(seeds=[seed]))

        matching = [e for e in result if e["slug"] == "retirement-basics"]
        assert len(matching) == 1
        assert matching[0]["source"] == "gsc"

    @patch("gsctopics.fetch_gsc.fetch_search_analytics")
    @patch("gsctopics.fetch_gsc.authenticate_gsc", return_value="tok")
    def test_min_impressions_filter_applied(self, _mock_auth, mock_fetch):
        low = dict(_valid_topic(), slug="low-signal")
        low["gsc_evidence"] = dict(low["gsc_evidence"], impressions=2.0)
        high = dict(_valid_topic(), slug="high-signal")
        high["gsc_evidence"] = dict(high["gsc_evidence"], impressions=50.0)
        mock_fetch.return_value = [high, low]

        result = fetch_gsc_topics({**self._config(), "min_impressions": 5})

        slugs = [e["slug"] for e in result]
        assert "high-signal" in slugs
        assert "low-signal" not in slugs


# ── TestLoadSeedTopics ────────────────────────────────────────────────────────

class TestLoadSeedTopics:
    def test_applies_defaults_for_terse_seeds(self):
        import datetime
        cfg = {"seed_topics": [{
            "slug": "how-to-build-an-emergency-fund",
            "category": "financial-tips",
            "target_keyword": "how to build an emergency fund",
        }]}

        seeds = load_seed_topics(cfg)

        assert len(seeds) == 1
        e = seeds[0]
        assert e["source"] == "wes"
        assert e["status"] == "suggested"
        assert e["gsc_evidence"] is None
        assert e["added_at"] == datetime.date.today().isoformat()

    def test_explicit_values_win_over_defaults(self):
        cfg = {"seed_topics": [{
            "slug": "x", "category": "retirement", "target_keyword": "y",
            "status": "consumed", "added_at": "2020-01-01", "source": "manual",
        }]}

        e = load_seed_topics(cfg)[0]

        assert e["status"] == "consumed"
        assert e["added_at"] == "2020-01-01"
        assert e["source"] == "manual"

    def test_terse_seeds_pass_schema_validation(self):
        cfg = {"seed_topics": [{
            "slug": "how-to-calculate-your-net-worth",
            "category": "financial-tips",
            "target_keyword": "how to calculate your net worth",
        }]}

        accepted, rejected = validate_topics(load_seed_topics(cfg))

        assert len(accepted) == 1
        assert len(rejected) == 0


# ── TestOpportunityScore ──────────────────────────────────────────────────────

class TestOpportunityScore:
    def test_higher_impressions_scores_higher(self):
        assert opportunity_score(100.0, 10.0) > opportunity_score(10.0, 10.0)

    def test_position_floor_prevents_division_by_zero(self):
        assert opportunity_score(50.0, 0.0) == 50.0


# ── TestIsQualityQuery ────────────────────────────────────────────────────────

class TestIsQualityQuery:
    @pytest.mark.parametrize("query", [
        "retirement planning basics",
        "401k contribution limits",
        "roth ira limits",
        "coast fire calculator",
        "how to invest",
    ])
    def test_keeps_article_worthy_queries(self, query):
        assert is_quality_query(query) is True

    @pytest.mark.parametrize("query", [
        '"rsxfs" "2025-01" before:2025-12-28',   # operator + date + quotes + gibberish
        '"exhoslusm495s" "2025-02-01" before april 2025',  # date + quotes
        '"born in 1960 or later" "rmd age 75"',  # quoted exact-match noise
        "rsxfs",                                  # single vowel-less gibberish token
        "site:deanfi.com",                        # search operator
        "",                                       # empty
        "   ",                                    # whitespace only
    ])
    def test_drops_export_noise(self, query):
        assert is_quality_query(query) is False


# ── TestAssignCategory ────────────────────────────────────────────────────────

class TestAssignCategory:
    def test_matches_despite_surrounding_quotes(self):
        # Quoted exact-match queries must still resolve to the right category
        # rather than silently falling back to the market-education default.
        assert assign_category('"rmd age 75"') == "retirement"
        assert assign_category('"mortgage refinance rates"') == "debt"

    def test_unmatched_defaults_to_market_education(self):
        assert assign_category("stock market breadth explained") == "market-education"


# ── TestValidateTopics ────────────────────────────────────────────────────────

class TestValidateTopics:
    def test_valid_gsc_entry_accepted(self):
        accepted, rejected = validate_topics([_valid_topic()])
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_missing_required_field_rejected(self):
        bad = _valid_topic()
        del bad["slug"]
        accepted, rejected = validate_topics([bad])
        assert len(accepted) == 0
        assert len(rejected) == 1

    def test_invalid_category_rejected(self):
        bad = _valid_topic()
        bad["category"] = "not-a-real-category"
        _, rejected = validate_topics([bad])
        assert len(rejected) == 1

    def test_wes_seed_with_null_gsc_evidence_accepted(self):
        seed = {
            "slug": "seed-topic",
            "category": "financial-tips",
            "target_keyword": "seed keyword",
            "added_at": "2026-06-10",
            "status": "suggested",
            "source": "wes",
            "gsc_evidence": None,
        }
        accepted, rejected = validate_topics([seed])
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_rejection_log_contains_reason(self, caplog):
        bad = _valid_topic()
        bad["category"] = "invalid-cat"
        import logging
        with caplog.at_level(logging.WARNING):
            validate_topics([bad])
        assert "invalid category" in caplog.text


# ── TestRunGSCTopics ──────────────────────────────────────────────────────────

class TestRunGSCTopics:
    @patch("gsctopics.run_gsc_topics.fetch_gsc_topics")
    @patch("gsctopics.run_gsc_topics.load_config")
    def test_keeps_lastgood_and_exits_nonzero_on_source_fetch_error(
        self, mock_cfg, mock_fetch, tmp_path
    ):
        lastgood = tmp_path / "topics.json"
        lastgood.write_text('[{"existing": true}]')
        mock_cfg.return_value = {}
        mock_fetch.side_effect = SourceFetchError("GSC API auth error: HTTP 401")

        with pytest.raises(SystemExit) as exc_info:
            run(str(lastgood))
        assert exc_info.value.code == 1
        assert json.loads(lastgood.read_text()) == [{"existing": True}]

    @patch("gsctopics.run_gsc_topics.fetch_gsc_topics")
    @patch("gsctopics.run_gsc_topics.load_config")
    def test_writes_output_when_all_succeeds(self, mock_cfg, mock_fetch, tmp_path):
        out = tmp_path / "topics.json"
        mock_cfg.return_value = {}
        mock_fetch.return_value = [_valid_topic()]

        run(str(out))

        written = json.loads(out.read_text())
        assert len(written) == 1
        assert written[0]["slug"] == "roth-ira-limits"

    @patch("gsctopics.run_gsc_topics.fetch_gsc_topics")
    @patch("gsctopics.run_gsc_topics.load_config")
    def test_exits_nonzero_when_zero_valid_topics(self, mock_cfg, mock_fetch, tmp_path):
        out = tmp_path / "topics.json"
        mock_cfg.return_value = {}
        mock_fetch.return_value = [{"broken": True}]  # fails validation

        with pytest.raises(SystemExit) as exc_info:
            run(str(out))
        assert exc_info.value.code == 1
        assert not out.exists()

    @patch("gsctopics.run_gsc_topics.fetch_gsc_topics")
    @patch("gsctopics.run_gsc_topics.load_config")
    def test_missing_env_var_exits_nonzero_without_writing(self, mock_cfg, mock_fetch, tmp_path):
        out = tmp_path / "topics.json"
        mock_cfg.return_value = {}
        mock_fetch.side_effect = SourceFetchError("GSC credentials not set: GSC_CLIENT_ID")

        with pytest.raises(SystemExit) as exc_info:
            run(str(out))
        assert exc_info.value.code == 1
        assert not out.exists()
