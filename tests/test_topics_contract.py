"""
topics.json contract: the gate that decides which entries reach topics.json.

deanfi-website's topic selector (scripts/education/topics/select-topic.mjs)
maps these slug-form categories to content labels and skips status "consumed".
An entry outside this contract must never be written.
"""
import pytest

from gsctopics.gsc_topics_utils import validate_topics

# Mirrors CATEGORY_LABELS keys in deanfi-website select-topic.mjs; listed here
# (not imported from the collector) so the two sides cannot drift silently.
WEBSITE_CATEGORIES = ("market-education", "retirement", "debt", "financial-tips")
CONTRACT_FIELDS = ("slug", "category", "target_keyword", "added_at", "status")


def _valid_topic(**overrides):
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
    base.update(overrides)
    return base


@pytest.mark.parametrize("category", WEBSITE_CATEGORIES)
@pytest.mark.parametrize("status", ["suggested", "consumed"])
def test_entry_in_website_vocabulary_is_accepted(category, status):
    accepted, rejected = validate_topics([_valid_topic(category=category, status=status)])
    assert len(accepted) == 1 and rejected == []


def test_seed_entry_without_gsc_evidence_is_accepted():
    accepted, rejected = validate_topics([_valid_topic(source="wes", gsc_evidence=None)])
    assert len(accepted) == 1 and rejected == []


@pytest.mark.parametrize("field", CONTRACT_FIELDS)
@pytest.mark.parametrize("mode", ["missing", "null"])
def test_entry_without_contract_field_is_rejected(field, mode):
    bad = _valid_topic()
    if mode == "missing":
        del bad[field]
    else:
        bad[field] = None
    _, rejected = validate_topics([bad])
    assert len(rejected) == 1


@pytest.mark.parametrize("overrides", [
    {"category": "cross-cutting"},       # valid for facts, not for topics
    {"category": "Retirement Planning"},  # website label, not the slug form
    {"status": "pending"},
], ids=["facts-only-category", "label-category", "unknown-status"])
def test_entry_outside_vocabulary_is_rejected(overrides):
    _, rejected = validate_topics([_valid_topic(**overrides)])
    assert len(rejected) == 1


def test_incomplete_gsc_evidence_is_rejected(caplog):
    bad = _valid_topic()
    del bad["gsc_evidence"]["avg_position"]
    _, rejected = validate_topics([bad])
    assert len(rejected) == 1
    assert "avg_position" in caplog.text
