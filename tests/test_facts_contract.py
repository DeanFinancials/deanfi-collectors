"""
C1b facts-artifact schema-contract tests (Issue 09).

Validates that:
  - Every record in a produced facts.json has required fields with correct types (AC1)
  - The freshness check detects stale records and would cause exit non-zero (AC3)

AC2 (R2 reachability) is verified by manual curl:
  curl -sI https://r2.deanfi.com/education/facts.json → HTTP 200 ✅ (2026-06-10)
"""
import datetime

import pytest

from educationfacts.education_facts_utils import (
    CATEGORY_ENUM,
    REQUIRED_FIELDS,
    check_facts_freshness,
    validate_records,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

def _valid_fact(overrides=None):
    base = {
        "id": "fred-fed-funds-rate",
        "category": "market-education",
        "claim": "Federal funds effective rate",
        "value": 5.33,
        "unit": "%",
        "source_name": "Federal Reserve",
        "source_url": "https://www.federalreserve.gov/releases/h15/",
        "as_of": "2026-05-01",
        "max_age_days": 45,
    }
    if overrides:
        base.update(overrides)
    return base


def _facts_fixture():
    """A minimal valid facts.json covering all 5 category enum values."""
    return [
        _valid_fact({"id": "fred-fed-funds-rate", "category": "market-education"}),
        _valid_fact({"id": "irs-401k-employee-limit-2026", "category": "retirement",
                     "value": 24500, "unit": "USD"}),
        _valid_fact({"id": "fred-30yr-mortgage-pmms", "category": "debt",
                     "value": 6.87, "unit": "%"}),
        _valid_fact({"id": "irs-std-deduction-single-2026", "category": "financial-tips",
                     "value": 15750, "unit": "USD"}),
        _valid_fact({"id": "bea-gdp-growth-pct", "category": "cross-cutting",
                     "value": 2.8, "unit": "%"}),
    ]


# ── TestFactsSchemaContract ───────────────────────────────────────────────────

class TestFactsSchemaContract:
    def test_all_required_fields_present_on_valid_fixture(self):
        facts = _facts_fixture()
        accepted, rejected = validate_records(facts)
        assert rejected == [], f"Unexpected rejections: {[r.get('id') for r in rejected]}"
        assert len(accepted) == len(facts)

    def test_missing_required_field_is_rejected(self):
        bad = _valid_fact()
        del bad["source_url"]
        _, rejected = validate_records([bad])
        assert len(rejected) == 1

    def test_null_required_field_is_rejected(self):
        bad = _valid_fact({"as_of": None})
        _, rejected = validate_records([bad])
        assert len(rejected) == 1

    def test_category_enum_covers_all_five_values(self):
        """Every produced category value must be in the enum."""
        for cat in CATEGORY_ENUM:
            f = _valid_fact({"id": f"test-{cat}", "category": cat})
            accepted, rejected = validate_records([f])
            assert accepted, f"Category '{cat}' unexpectedly rejected"

    def test_value_field_is_numeric_in_valid_fixture(self):
        accepted, _ = validate_records(_facts_fixture())
        assert all(isinstance(r["value"], (int, float)) for r in accepted), (
            "Schema contract: every accepted fact's value must be int or float"
        )

    def test_required_fields_constant_matches_spec(self):
        expected = {"id", "category", "claim", "value", "unit",
                    "source_name", "source_url", "as_of", "max_age_days"}
        assert REQUIRED_FIELDS == frozenset(expected)

    def test_at_least_one_record_per_category(self):
        facts = _facts_fixture()
        categories_present = {f["category"] for f in facts}
        assert CATEGORY_ENUM.issubset(categories_present), (
            f"Missing categories in fixture: {CATEGORY_ENUM - categories_present}"
        )


# ── TestFactsFreshness ────────────────────────────────────────────────────────

class TestFactsFreshness:
    def test_fresh_records_return_empty_stale_list(self):
        today = datetime.date(2026, 6, 10)
        facts = [_valid_fact({"id": "test", "as_of": "2026-05-20", "max_age_days": 45})]
        stale = check_facts_freshness(facts, today=today)
        # 21 days ago, max_age_days=45 → fresh
        assert stale == []

    def test_stale_record_appears_in_stale_list(self):
        """AC3: injecting as_of = 40 days ago with max_age_days=30 → stale."""
        today = datetime.date(2026, 6, 10)
        stale_date = (today - datetime.timedelta(days=40)).isoformat()
        facts = [_valid_fact({"id": "stale-fact", "as_of": stale_date, "max_age_days": 30})]
        stale = check_facts_freshness(facts, today=today)
        assert "stale-fact" in stale

    def test_current_tax_year_record_can_exceed_source_age_budget(self):
        today = datetime.date(2026, 6, 20)
        facts = [
            _valid_fact({
                "id": "irs-hsa-individual-limit-2026",
                "as_of": "2025-05-15",
                "max_age_days": 400,
                "tax_year": 2026,
            })
        ]

        stale = check_facts_freshness(facts, today=today)

        assert stale == []

    def test_prior_tax_year_record_still_fails_when_source_age_exceeds_budget(self):
        today = datetime.date(2026, 6, 20)
        facts = [
            _valid_fact({
                "id": "irs-hsa-individual-limit-2025",
                "as_of": "2025-05-15",
                "max_age_days": 400,
                "tax_year": 2025,
            })
        ]

        stale = check_facts_freshness(facts, today=today)

        assert stale == ["irs-hsa-individual-limit-2025"]

    def test_stale_list_nonempty_would_cause_exit_nonzero(self):
        """Confirms the CI contract: len(stale) > 0 means the check fails."""
        today = datetime.date(2026, 6, 10)
        stale_date = (today - datetime.timedelta(days=40)).isoformat()
        facts = [_valid_fact({"id": "stale-fact", "as_of": stale_date, "max_age_days": 30})]
        stale = check_facts_freshness(facts, today=today)
        # In CI: if stale: sys.exit(1)
        assert len(stale) > 0, "Expected stale list to be non-empty for this fixture"

    def test_exactly_at_boundary_is_fresh(self):
        today = datetime.date(2026, 6, 10)
        boundary_date = (today - datetime.timedelta(days=30)).isoformat()
        facts = [_valid_fact({"id": "boundary", "as_of": boundary_date, "max_age_days": 30})]
        stale = check_facts_freshness(facts, today=today)
        assert stale == []  # exactly at boundary is fresh (≤ not <)

    def test_bad_as_of_format_silently_skipped(self):
        facts = [_valid_fact({"id": "bad-date", "as_of": "not-a-date"})]
        stale = check_facts_freshness(facts)
        assert "bad-date" not in stale
