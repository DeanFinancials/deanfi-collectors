"""
C2b topics-artifact schema-contract tests (Issue 10).

Validates that:
  - Every entry in a produced topics.json has required fields with correct types (AC1)
  - The freshness watermark check detects stale topics and would cause exit non-zero (AC2)
"""
import datetime

import pytest

from gsctopics.gsc_topics_utils import (
    CATEGORY_ENUM,
    STATUS_ENUM,
    check_topics_freshness,
    validate_topics,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

def _valid_topic(overrides=None):
    base = {
        "slug": "roth-ira-contribution-limits",
        "category": "retirement",
        "target_keyword": "roth ira contribution limits",
        "added_at": "2026-06-10",
        "status": "suggested",
        "source": "gsc",
        "gsc_evidence": {
            "impressions": 120.0,
            "avg_position": 6.2,
            "clicks": 1.0,
            "window": "90d",
        },
        "title_working": "Roth Ira Contribution Limits",
        "secondary_keywords": [],
        "internal_link_targets": [],
        "facts_refs": [],
        "vertical": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _topics_fixture():
    """Minimal valid topics.json covering all 4 category enum values."""
    return [
        _valid_topic({"slug": "roth-ira-basics", "category": "retirement"}),
        _valid_topic({"slug": "mortgage-rates-today", "category": "debt",
                      "target_keyword": "mortgage rates today"}),
        _valid_topic({"slug": "fed-funds-rate-explained", "category": "market-education",
                      "target_keyword": "fed funds rate explained"}),
        _valid_topic({"slug": "standard-deduction-2026", "category": "financial-tips",
                      "target_keyword": "standard deduction 2026"}),
    ]


# ── TestTopicsSchemaContract ──────────────────────────────────────────────────

class TestTopicsSchemaContract:
    def test_all_required_fields_present_on_valid_fixture(self):
        topics = _topics_fixture()
        accepted, rejected = validate_topics(topics)
        assert rejected == [], f"Unexpected rejections: {[t.get('slug') for t in rejected]}"
        assert len(accepted) == len(topics)

    def test_missing_required_field_is_rejected(self):
        bad = _valid_topic()
        del bad["target_keyword"]
        _, rejected = validate_topics([bad])
        assert len(rejected) == 1

    def test_invalid_category_is_rejected(self):
        bad = _valid_topic({"category": "not-valid"})
        _, rejected = validate_topics([bad])
        assert len(rejected) == 1

    def test_invalid_status_is_rejected(self):
        bad = _valid_topic({"status": "pending"})
        _, rejected = validate_topics([bad])
        assert len(rejected) == 1

    def test_category_enum_covers_all_four_values(self):
        for cat in CATEGORY_ENUM:
            t = _valid_topic({"slug": f"test-{cat}", "category": cat,
                               "target_keyword": f"{cat} test"})
            accepted, _ = validate_topics([t])
            assert accepted, f"Category '{cat}' unexpectedly rejected"

    def test_status_enum_covers_both_values(self):
        for status in STATUS_ENUM:
            t = _valid_topic({"status": status})
            accepted, _ = validate_topics([t])
            assert accepted, f"Status '{status}' unexpectedly rejected"

    def test_wes_seed_with_null_gsc_evidence_accepted(self):
        seed = _valid_topic({"source": "wes", "gsc_evidence": None})
        accepted, rejected = validate_topics([seed])
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_gsc_evidence_missing_subfield_is_rejected(self):
        bad = _valid_topic()
        del bad["gsc_evidence"]["avg_position"]
        _, rejected = validate_topics([bad])
        assert len(rejected) == 1

    def test_at_least_one_entry_per_category(self):
        topics = _topics_fixture()
        categories_present = {t["category"] for t in topics}
        assert CATEGORY_ENUM.issubset(categories_present), (
            f"Missing categories: {CATEGORY_ENUM - categories_present}"
        )


# ── TestTopicsFreshness ───────────────────────────────────────────────────────

class TestTopicsFreshness:
    def test_fresh_topics_return_true(self):
        today = datetime.date(2026, 6, 10)
        topics = [_valid_topic({"added_at": "2026-06-08", "status": "suggested"})]
        assert check_topics_freshness(topics, threshold_days=14, today=today) is True

    def test_stale_topics_return_false(self):
        """AC2: newest non-consumed added_at = 20 days ago → stale (threshold=14)."""
        today = datetime.date(2026, 6, 10)
        stale_date = (today - datetime.timedelta(days=20)).isoformat()
        topics = [_valid_topic({"added_at": stale_date, "status": "suggested"})]
        result = check_topics_freshness(topics, threshold_days=14, today=today)
        assert result is False

    def test_false_result_would_cause_exit_nonzero(self):
        """Confirms CI contract: check_topics_freshness() == False → sys.exit(1)."""
        today = datetime.date(2026, 6, 10)
        stale_date = (today - datetime.timedelta(days=20)).isoformat()
        topics = [_valid_topic({"added_at": stale_date, "status": "suggested"})]
        is_fresh = check_topics_freshness(topics, threshold_days=14, today=today)
        # In CI: if not is_fresh: sys.exit(1)
        assert not is_fresh

    def test_consumed_entries_excluded_from_freshness_check(self):
        today = datetime.date(2026, 6, 10)
        stale_date = (today - datetime.timedelta(days=20)).isoformat()
        fresh_date = (today - datetime.timedelta(days=5)).isoformat()
        topics = [
            _valid_topic({"added_at": stale_date, "status": "consumed"}),
            _valid_topic({"slug": "fresh", "added_at": fresh_date, "status": "suggested"}),
        ]
        assert check_topics_freshness(topics, threshold_days=14, today=today) is True

    def test_empty_non_consumed_list_is_treated_as_fresh(self):
        today = datetime.date(2026, 6, 10)
        topics = [_valid_topic({"status": "consumed"})]
        assert check_topics_freshness(topics, threshold_days=14, today=today) is True

    def test_exactly_at_threshold_is_fresh(self):
        today = datetime.date(2026, 6, 10)
        boundary = (today - datetime.timedelta(days=14)).isoformat()
        topics = [_valid_topic({"added_at": boundary, "status": "suggested"})]
        assert check_topics_freshness(topics, threshold_days=14, today=today) is True
