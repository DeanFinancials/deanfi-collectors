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
