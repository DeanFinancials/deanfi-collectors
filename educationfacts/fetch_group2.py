"""
Group 2 — BLS / FRED / BEA.

Fetches live economic indicators:
  BLS  (BLS_API_KEY)  — unemployment rate, CPI all-urban index
  FRED (FRED_API_KEY) — fed funds rate, 10yr/2yr Treasury yields, 30yr PMMS
                        mortgage rate, national savings/CD rates, mortgage
                        delinquency rate, house price index
  BEA  (BEA_API_KEY, optional) — real GDP growth rate

AC4 compliance: HTTP status codes are logged on failure; API key values are
NEVER written to logs (keys are passed as query parameters or POST bodies,
never interpolated into log messages).
"""
import logging
import os
from datetime import datetime
from typing import Any, Optional

import requests

from .education_facts_utils import SourceFetchError, fetch_with_retry

logger = logging.getLogger(__name__)

# ── BLS ───────────────────────────────────────────────────────────────────────

_BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Series definitions: series_id → fact metadata
_BLS_SERIES: dict[str, dict] = {
    "LNS14000000": {
        "id": "bls-unemployment-rate",
        "category": "market-education",
        "claim": "US civilian unemployment rate (seasonally adjusted)",
        "unit": "%",
        "source_name": "Bureau of Labor Statistics",
        "source_url": "https://data.bls.gov/timeseries/LNS14000000",
        "max_age_days": 45,
    },
    "CUUR0000SA0": {
        "id": "bls-cpi-all-urban-index",
        "category": "market-education",
        "claim": "CPI-U all-items index (not seasonally adjusted; 1982-84=100)",
        "unit": "ratio",
        "source_name": "Bureau of Labor Statistics",
        "source_url": "https://data.bls.gov/timeseries/CUUR0000SA0",
        "max_age_days": 45,
    },
}

# Month code → zero-padded month string for date formatting
_PERIOD_TO_MONTH: dict[str, str] = {f"M{i:02d}": f"{i:02d}" for i in range(1, 13)}


def fetch_bls_series(
    series_ids: list[str],
    api_key: str,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> list[dict]:
    """
    Fetch the latest observations for the given BLS series.

    Raises SourceFetchError on non-2xx after all retries or on missing data.
    AC4: status codes are logged; api_key is never written to any log message.
    """
    import time as _time

    current_year = str(datetime.now().year)
    payload = {
        "seriesid": series_ids,
        "startyear": str(int(current_year) - 1),
        "endyear": current_year,
        "registrationkey": api_key,
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(_BLS_URL, json=payload, timeout=30)
            if resp.status_code == 200:
                break
            # Log status code only — never the key
            logger.warning(
                "BLS API HTTP %d (attempt %d/%d)", resp.status_code, attempt + 1, max_retries
            )
        except requests.RequestException as exc:
            logger.warning(
                "BLS transport error (attempt %d/%d): %s",
                attempt + 1, max_retries, type(exc).__name__,
            )
            resp = None  # type: ignore[assignment]

        if attempt < max_retries - 1:
            _time.sleep(base_delay * (2 ** attempt))
    else:
        raise SourceFetchError("BLS API failed after all retries")

    try:
        body = resp.json()
    except ValueError as exc:
        raise SourceFetchError(f"BLS API returned non-JSON body: {exc}") from exc

    records: list[dict] = []
    for series_data in body.get("Results", {}).get("series", []):
        sid = series_data.get("seriesID", "")
        if sid not in _BLS_SERIES:
            continue
        meta = _BLS_SERIES[sid]
        data_points = series_data.get("data", [])
        if not data_points:
            logger.warning("BLS series %s returned no data points", sid)
            continue

        # data is sorted most-recent first by BLS
        latest = data_points[0]
        try:
            value = float(latest["value"])
        except (KeyError, ValueError, TypeError):
            logger.warning("BLS series %s: unparseable value '%s'", sid, latest.get("value"))
            continue

        year = latest.get("year", "")
        period = latest.get("period", "M01")
        month = _PERIOD_TO_MONTH.get(period, "01")
        as_of = f"{year}-{month}-01" if year else ""

        records.append({
            "id": meta["id"],
            "category": meta["category"],
            "claim": meta["claim"],
            "value": value,
            "unit": meta["unit"],
            "source_name": meta["source_name"],
            "source_url": meta["source_url"],
            "as_of": as_of,
            "max_age_days": meta["max_age_days"],
        })

    return records


# ── FRED ──────────────────────────────────────────────────────────────────────

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# FRED series to collect: series_id → fact metadata
_FRED_SERIES: list[dict] = [
    {
        "series_id": "FEDFUNDS",
        "fact_id": "fred-fed-funds-rate",
        "category": "market-education",
        "claim": "Federal funds effective rate (monthly average)",
        "unit": "%",
        "source_name": "Federal Reserve",
        "source_url": "https://www.federalreserve.gov/releases/h15/",
        "max_age_days": 45,
    },
    {
        "series_id": "DGS10",
        "fact_id": "fred-10yr-treasury-yield",
        "category": "market-education",
        "claim": "10-Year Treasury Constant Maturity Rate",
        "unit": "%",
        "source_name": "US Treasury / Federal Reserve H.15",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/",
        "max_age_days": 14,
    },
    {
        "series_id": "DGS2",
        "fact_id": "fred-2yr-treasury-yield",
        "category": "market-education",
        "claim": "2-Year Treasury Constant Maturity Rate",
        "unit": "%",
        "source_name": "US Treasury / Federal Reserve H.15",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/",
        "max_age_days": 14,
    },
    {
        "series_id": "MORTGAGE30US",
        "fact_id": "fred-30yr-mortgage-pmms",
        "category": "debt",
        "claim": "Freddie Mac 30-Year Fixed Rate Mortgage Average (PMMS)",
        "unit": "%",
        "source_name": "Freddie Mac Primary Mortgage Market Survey",
        "source_url": "https://www.freddiemac.com/pmms",
        "max_age_days": 14,
    },
    # SAVRNJ and CD1NRNJ (FDIC national savings/CD rates) were discontinued in FRED
    # in 2021. Direct FDIC API integration is deferred to v2.
    {
        "series_id": "DRSFRMACBS",
        "fact_id": "fred-mortgage-delinquency",
        "category": "debt",
        "claim": "Delinquency rate on single-family residential mortgages (seasonally adjusted)",
        "unit": "%",
        "source_name": "Federal Reserve / Board of Governors",
        "source_url": "https://www.federalreserve.gov/releases/chargeoff/",
        # Quarterly series. With the quarter-start as_of convention, the newest
        # point legitimately ages ~1 quarter (~91d) + publication lag before the
        # next release supersedes it (~210-260d observed). 270d covers that worst
        # case + grace while still tripping Signal 3 if a quarter is fully missed.
        "max_age_days": 270,
    },
    {
        "series_id": "USSTHPI",
        "fact_id": "fred-hpi-all-transactions",
        "category": "debt",
        "claim": "FHFA All-Transactions House Price Index (seasonally adjusted, 1991 Q1=100)",
        "unit": "ratio",
        "source_name": "Federal Housing Finance Agency",
        "source_url": "https://www.fhfa.gov/data/hpi",
        # Quarterly (see fred-mortgage-delinquency note) → 270d budget.
        "max_age_days": 270,
    },
]


def fetch_fred_series(
    series_id: str,
    api_key: str,
    *,
    fact_id: str,
    category: str,
    claim: str,
    unit: str,
    source_name: str,
    source_url: str,
    max_age_days: int,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> dict:
    """
    Fetch the most recent observation for a single FRED series.

    Raises SourceFetchError if the API call fails or returns no observations.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "sort_order": "desc",
        "limit": "5",
        "file_type": "json",
    }
    data = fetch_with_retry(_FRED_BASE, params=params, max_retries=max_retries, base_delay=base_delay)
    if data is None:
        raise SourceFetchError(f"FRED series {series_id} failed after all retries")

    observations = data.get("observations", [])
    # FRED may return "." for missing values — skip them
    for obs in observations:
        raw_val = obs.get("value", ".")
        if raw_val == ".":
            continue
        try:
            value = float(raw_val)
        except (ValueError, TypeError):
            continue

        return {
            "id": fact_id,
            "category": category,
            "claim": claim,
            "value": value,
            "unit": unit,
            "source_name": source_name,
            "source_url": source_url,
            "as_of": obs.get("date", ""),
            "max_age_days": max_age_days,
        }

    raise SourceFetchError(f"FRED series {series_id}: no non-null observations returned")


def _fetch_all_fred(api_key: str) -> list[dict]:
    """Fetch all configured FRED series; raise SourceFetchError if any fail."""
    records: list[dict] = []
    failed: list[str] = []

    for meta in _FRED_SERIES:
        try:
            rec = fetch_fred_series(
                series_id=meta["series_id"],
                api_key=api_key,
                fact_id=meta["fact_id"],
                category=meta["category"],
                claim=meta["claim"],
                unit=meta["unit"],
                source_name=meta["source_name"],
                source_url=meta["source_url"],
                max_age_days=meta["max_age_days"],
            )
            records.append(rec)
        except SourceFetchError as exc:
            logger.error("FRED series %s failed: %s", meta["series_id"], exc)
            failed.append(meta["series_id"])

    if failed:
        raise SourceFetchError(f"FRED series failed: {', '.join(failed)}")

    return records


# ── BEA (optional) ────────────────────────────────────────────────────────────

_BEA_URL = "https://apps.bea.gov/api/data/"


def fetch_bea_gdp(api_key: str) -> Optional[dict]:
    """
    Fetch the most recent real GDP growth rate from BEA NIPA.

    Returns None (silently skips) if api_key is empty, rather than raising
    SourceFetchError — BEA is optional in v1.  Raises SourceFetchError on
    a genuine API failure when a key is present.
    """
    if not api_key:
        logger.info("BEA_API_KEY not set — skipping GDP growth fact")
        return None

    params = {
        "UserID": api_key,
        "method": "GetData",
        "datasetname": "NIPA",
        "TableName": "T10101",
        "Frequency": "Q",
        "Year": "X",  # most recent year
        "ResultFormat": "JSON",
    }
    data = fetch_with_retry(_BEA_URL, params=params)
    if data is None:
        raise SourceFetchError("BEA API failed after all retries")

    try:
        rows = data["BEAAPI"]["Results"]["Data"]
        # T10101 L1 = Real GDP (annualized % change); find most recent Q
        gdp_rows = [
            r for r in rows
            if r.get("LineNumber") == "1" and r.get("SeriesCode") == "A191RL"
        ]
        if not gdp_rows:
            raise SourceFetchError("BEA: no GDP row found in T10101 L1")

        latest = gdp_rows[-1]
        value = float(latest["DataValue"].replace(",", ""))
        time_period = latest.get("TimePeriod", "")
        # TimePeriod format: "2026Q1" → as_of "2026-01-01"
        year_str = time_period[:4] if len(time_period) >= 4 else ""
        quarter = time_period[4:] if len(time_period) >= 6 else "Q1"
        month_map = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
        as_of = f"{year_str}-{month_map.get(quarter, '01')}-01" if year_str else ""

        return {
            "id": "bea-gdp-growth-pct",
            "category": "cross-cutting",
            "claim": "Real GDP growth rate (annualized, seasonally adjusted annual rate)",
            "value": value,
            "unit": "%",
            "source_name": "Bureau of Economic Analysis",
            "source_url": "https://www.bea.gov/data/gdp/gross-domestic-product",
            "as_of": as_of,
            # Quarterly (see fred-mortgage-delinquency note) → 270d budget.
            "max_age_days": 270,
        }

    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise SourceFetchError(f"BEA: unexpected response structure: {exc}") from exc


# ── Entry point ───────────────────────────────────────────────────────────────

def fetch_group2(config: dict) -> list[dict]:  # noqa: ARG001  (config reserved for future use)
    """
    Return all Group 2 fact records from BLS, FRED, and optionally BEA.

    API keys are read from environment variables (injected by GH Actions secrets).
    Raises SourceFetchError if BLS or FRED fail; BEA failure is silently skipped
    if the key is absent, otherwise raises.
    """
    bls_key = os.environ.get("BLS_API_KEY", "")
    fred_key = os.environ.get("FRED_API_KEY", "")
    bea_key = os.environ.get("BEA_API_KEY", "")

    if not bls_key:
        raise SourceFetchError("BLS_API_KEY environment variable is not set")
    if not fred_key:
        raise SourceFetchError("FRED_API_KEY environment variable is not set")

    records: list[dict] = []

    bls_records = fetch_bls_series(list(_BLS_SERIES.keys()), api_key=bls_key)
    records.extend(bls_records)

    fred_records = _fetch_all_fred(api_key=fred_key)
    records.extend(fred_records)

    bea_record = fetch_bea_gdp(api_key=bea_key)
    if bea_record:
        records.append(bea_record)

    return records
