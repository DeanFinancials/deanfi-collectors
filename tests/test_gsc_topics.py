"""
GSC topics collector: fail closed so a bad run never replaces the last-good
topics.json, keep tokens out of logs, and keep export noise out of the topic
pool the website draws articles from. Entry-level contract checks live in
test_topics_contract.py.
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
    @pytest.mark.parametrize("missing", [
        ("GSC_CLIENT_ID", "GSC_CLIENT_SECRET", "GSC_REFRESH_TOKEN"),
        ("GSC_REFRESH_TOKEN",),
    ], ids=["all", "one"])
    def test_missing_credentials_raise_source_fetch_error(self, monkeypatch, missing):
        _gsc_env(monkeypatch)
        for name in missing:
            monkeypatch.delenv(name)

        with pytest.raises(SourceFetchError, match=missing[-1]):
            authenticate_gsc()

    @patch("gsctopics.fetch_gsc.GoogleRequest")
    @patch("gsctopics.fetch_gsc.Credentials")
    def test_revoked_refresh_token_raises_source_fetch_error(
        self, mock_creds_cls, _mock_req_cls, monkeypatch
    ):
        _gsc_env(monkeypatch)
        from google.auth.exceptions import RefreshError
        mock_creds_cls.return_value.refresh.side_effect = RefreshError("invalid_grant")

        with pytest.raises(SourceFetchError, match="token refresh failed"):
            authenticate_gsc()


# ── TestFetchSearchAnalytics ──────────────────────────────────────────────────

def _respond(mock_post, rows=None, status_code=200, body=None):
    payload = body if body is not None else _gsc_response(rows or [])
    mock_post.return_value = MagicMock(status_code=status_code, json=lambda: payload)


class TestFetchSearchAnalytics:
    @patch("gsctopics.fetch_gsc.requests.post")
    def test_returns_contract_valid_entries_ranked_without_noise_or_covered_pages(self, mock_post):
        _respond(mock_post, [
            _gsc_row("roth ira guide", "https://deanfi.com/insights/roth-ira/", impressions=500),
            _gsc_row('"rsxfs" "2025-01" before:2025-12-28', "https://deanfi.com/", impressions=900),
            _gsc_row("retirement planning basics", "https://deanfi.com/retirement/", impressions=50),
            _gsc_row("401k contribution limits", "https://deanfi.com/retirement/", impressions=150),
        ])

        results = fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, ["/insights/"])

        assert [e["target_keyword"] for e in results] == [
            "401k contribution limits", "retirement planning basics",
        ]
        accepted, rejected = validate_topics(results)
        assert rejected == [] and len(accepted) == 2
        assert {(e["status"], e["source"]) for e in results} == {("suggested", "gsc")}

    @patch("gsctopics.fetch_gsc.requests.post")
    def test_absent_rows_is_empty_not_an_error(self, mock_post):
        _respond(mock_post, body={})
        assert fetch_search_analytics("tok", "sc-domain:deanfi.com", 90, []) == []

    @patch("gsctopics.fetch_gsc.time.sleep", return_value=None)
    @patch("gsctopics.fetch_gsc.requests.post")
    def test_401_raises_and_logs_status_code_not_token(self, mock_post, _mock_sleep, caplog):
        mock_post.return_value = MagicMock(status_code=401)
        secret_token = "super_secret_access_token_value"

        import logging
        with caplog.at_level(logging.WARNING, logger="gsctopics.fetch_gsc"):
            with pytest.raises(SourceFetchError, match="HTTP 401"):
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
        accepted, rejected = validate_topics(seeds)
        assert len(accepted) == 1 and rejected == []

    def test_explicit_values_win_over_defaults(self):
        cfg = {"seed_topics": [{
            "slug": "x", "category": "retirement", "target_keyword": "y",
            "status": "consumed", "added_at": "2020-01-01", "source": "manual",
        }]}

        e = load_seed_topics(cfg)[0]

        assert e["status"] == "consumed"
        assert e["added_at"] == "2020-01-01"
        assert e["source"] == "manual"


# ── TestOpportunityScore ──────────────────────────────────────────────────────

class TestOpportunityScore:
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
    def test_writes_only_valid_topics(self, mock_cfg, mock_fetch, tmp_path):
        out = tmp_path / "topics.json"
        mock_cfg.return_value = {}
        mock_fetch.return_value = [_valid_topic(), dict(_valid_topic(), slug="bad", category="nope")]

        run(str(out))

        assert [t["slug"] for t in json.loads(out.read_text())] == ["roth-ira-limits"]

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
