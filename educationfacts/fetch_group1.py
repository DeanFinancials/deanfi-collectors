"""
Group 1 — Treasury / FHFA.

Treasury average interest rates on outstanding Treasury Notes and Bonds are
fetched from the US Treasury Fiscal Data API (no API key required).  FHFA
conforming loan limit is sourced from config seeds (annual announcement).

Raises SourceFetchError if the Treasury API fetch fails after all retries.
"""
import logging
from datetime import datetime

from .education_facts_utils import SourceFetchError, fetch_with_retry, load_config

logger = logging.getLogger(__name__)

_TREASURY_API = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"
    "?fields=record_date,security_desc,avg_interest_rate_amt"
    "&filter=security_desc:in:(Treasury%20Notes,Treasury%20Bonds)"
    "&sort=-record_date"
    "&page%5Bsize%5D=20"
)

# Fact metadata keyed by security_desc value returned by the API
_SECURITY_META: dict[str, dict] = {
    "Treasury Notes": {
        "id": "treasury-notes-avg-rate",
        "category": "market-education",
        "claim": "Average interest rate on outstanding US Treasury Notes",
        "unit": "%",
        "source_name": "US Treasury Fiscal Data",
        "source_url": "https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        "max_age_days": 45,
    },
    "Treasury Bonds": {
        "id": "treasury-bonds-avg-rate",
        "category": "market-education",
        "claim": "Average interest rate on outstanding US Treasury Bonds",
        "unit": "%",
        "source_name": "US Treasury Fiscal Data",
        "source_url": "https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        "max_age_days": 45,
    },
}


def fetch_treasury_rates(max_retries: int = 3, base_delay: float = 2.0) -> list[dict]:
    """
    Return Treasury Notes and Bonds average interest rate records.

    Raises SourceFetchError if the API call fails after all retries.
    """
    data = fetch_with_retry(_TREASURY_API, max_retries=max_retries, base_delay=base_delay)
    if data is None:
        raise SourceFetchError("Treasury Fiscal Data API failed after all retries")

    rows = data.get("data", [])
    seen: set[str] = set()
    records: list[dict] = []

    for row in rows:
        desc = row.get("security_desc", "")
        if desc not in _SECURITY_META or desc in seen:
            continue
        seen.add(desc)

        rate_str = row.get("avg_interest_rate_amt", "")
        try:
            rate = float(rate_str)
        except (ValueError, TypeError):
            logger.warning("Treasury: unparseable rate value '%s' for %s — skipping", rate_str, desc)
            continue

        meta = _SECURITY_META[desc]
        records.append({
            "id": meta["id"],
            "category": meta["category"],
            "claim": meta["claim"],
            "value": rate,
            "unit": meta["unit"],
            "source_name": meta["source_name"],
            "source_url": meta["source_url"],
            "as_of": row.get("record_date", ""),
            "max_age_days": meta["max_age_days"],
        })

        if len(seen) == len(_SECURITY_META):
            break  # Got one record per security type

    if not records:
        raise SourceFetchError("Treasury API returned no parseable rate records")

    return records


def fetch_group1(config: dict) -> list[dict]:  # noqa: ARG001
    """
    Return all Group 1 fact records: Treasury rates (best-effort for v1).

    Group 1 is best-effort: if the Treasury API is unreachable or returns an
    unexpected response, a warning is logged and an empty list is returned.
    This does NOT trigger the last-good / exit-nonzero path — Group 1 enriches
    the fact library but is not required for core pipeline operation.

    v1 note: FDIC national deposit rates (SAVRNJ/CD1NRNJ) were discontinued
    in FRED in 2021 and direct FDIC API integration is deferred to v2.
    CFPB delinquency data and FHFA HPI are covered by FRED series in Group 2.
    """
    try:
        return fetch_treasury_rates()
    except SourceFetchError as exc:
        logger.warning(
            "Group 1 (Treasury) fetch failed — skipping (best-effort source): %s", exc
        )
        return []
