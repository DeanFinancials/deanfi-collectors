"""
facts.json contract: the gate that decides which records reach education/facts.json.

deanfi-website's education pipeline (scripts/education/pre-gate.mjs and
freshness-probe.mjs) reads these fields from every record on R2, so a record
missing any of them must never be written.
"""
import pytest

from educationfacts.education_facts_utils import validate_records

# Fields the website consumes; listed here (not imported) so shrinking the
# collector's REQUIRED_FIELDS breaks this test instead of silently loosening it.
CONTRACT_FIELDS = (
    "id", "category", "claim", "value", "unit",
    "source_name", "source_url", "as_of", "max_age_days",
)


def _valid_fact(**overrides):
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
    base.update(overrides)
    return base


@pytest.mark.parametrize("category", [
    "market-education", "retirement", "debt", "financial-tips", "cross-cutting",
])
def test_complete_fact_is_accepted(category):
    accepted, rejected = validate_records([_valid_fact(category=category)])
    assert len(accepted) == 1 and rejected == []


@pytest.mark.parametrize("field", CONTRACT_FIELDS)
@pytest.mark.parametrize("mode", ["missing", "null"])
def test_fact_without_contract_field_is_rejected(field, mode):
    bad = _valid_fact()
    if mode == "missing":
        del bad[field]
    else:
        bad[field] = None

    accepted, rejected = validate_records([bad, _valid_fact(id="sibling")])

    assert [r["id"] for r in accepted] == ["sibling"]
    assert len(rejected) == 1


# The website buckets facts by category (scripts/education/topics/select-topic.mjs
# CATEGORY_LABELS plus cross-cutting); anything else must not reach R2.
@pytest.mark.parametrize("category", ["Market Education", "investing", ""])
def test_fact_outside_category_vocabulary_is_rejected(category):
    accepted, rejected = validate_records([_valid_fact(category=category)])
    assert accepted == [] and len(rejected) == 1


@pytest.mark.parametrize("value", ["5.33", "", True, float("nan"), float("inf"), [5.33]],
                         ids=["numeric-string", "empty-string", "bool", "nan", "inf", "list"])
def test_numeric_fact_without_finite_number_value_is_rejected(value):
    accepted, rejected = validate_records([_valid_fact(value=value)])
    assert accepted == [] and len(rejected) == 1


@pytest.mark.parametrize("value, ok", [("67 years", True), ("  ", False), (67, False)])
def test_text_fact_value_must_be_non_empty_string(value, ok):
    accepted, _ = validate_records([_valid_fact(unit="text", value=value)])
    assert bool(accepted) is ok


@pytest.mark.parametrize("as_of", ["", "not-a-date", "2026-13-01", "2026-02-30", "20260501", "2026-05", 20260501],
                         ids=["empty", "word", "month-13", "feb-30", "compact", "year-month", "int"])
def test_fact_with_unparseable_as_of_is_rejected(as_of):
    """freshness-probe.mjs fails the whole probe with facts/invalid-as-of on these."""
    accepted, rejected = validate_records([_valid_fact(as_of=as_of)])
    assert accepted == [] and len(rejected) == 1


def test_records_shaped_like_every_emitter_are_accepted():
    """One record per producer shape: Treasury/FRED float, BLS float, seed int
    with tax_year, and the seed text fact. Guards against the new checks
    dropping data the website currently receives."""
    records = [
        _valid_fact(id="treasury-notes-avg-rate", value=3.283),
        _valid_fact(id="bls-unemployment-rate", value=4.3, as_of="2026-05-01"),
        _valid_fact(id="irs-401k-limit", category="retirement", value=24500, unit="USD", tax_year=2026),
        _valid_fact(id="ssa-full-retirement-age-note", category="retirement", value="67 years", unit="text"),
        _valid_fact(id="cfpb-tip", category="cross-cutting", value=0, unit="count"),
    ]
    accepted, rejected = validate_records(records)
    assert accepted == records and rejected == []
