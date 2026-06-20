"""
Shared utilities for the education-facts collector.

Provides: retry-with-backoff HTTP fetch, record validation (required fields +
sane bounds), facts JSON writer, and config loader.
"""
import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = frozenset(
    {"id", "category", "claim", "value", "unit", "source_name", "source_url", "as_of", "max_age_days"}
)

CATEGORY_ENUM = frozenset(
    {"market-education", "retirement", "debt", "financial-tips", "cross-cutting"}
)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"


class SourceFetchError(RuntimeError):
    """Raised when a source API fails after all retries are exhausted."""


def load_config(config_path: Optional[str] = None) -> dict:
    path = Path(config_path) if config_path else _CONFIG_PATH
    return yaml.safe_load(path.read_text())


def fetch_with_retry(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> Optional[dict]:
    """
    GET (or POST) a URL with exponential-backoff retry.

    Returns parsed JSON on success; None if all retries are exhausted.
    Logs HTTP status codes on failure — never logs credential values.
    """
    for attempt in range(max_retries):
        final_attempt = attempt == max_retries - 1
        try:
            if method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=json_body, timeout=30)
            else:
                resp = requests.get(url, headers=headers, params=params, timeout=30)

            if resp.status_code == 200:
                return resp.json()

            logger.log(
                logging.WARNING if final_attempt else logging.INFO,
                "HTTP %d from %s (attempt %d/%d)",
                resp.status_code, url, attempt + 1, max_retries,
            )

        except requests.RequestException as exc:
            logger.log(
                logging.WARNING if final_attempt else logging.INFO,
                "Transport error from %s (attempt %d/%d): %s",
                url, attempt + 1, max_retries, type(exc).__name__,
            )

        if attempt < max_retries - 1:
            time.sleep(base_delay * (2 ** attempt))

    return None


def validate_records(
    records: list[dict],
    sane_bounds: Optional[dict] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Split records into (accepted, rejected).

    A record is rejected if any required field is absent/null, or if its
    numeric value falls outside the configured sane bounds.  Rejected records
    are logged with field name + observed value so CI output is auditable.
    """
    sane_bounds = sane_bounds or {}
    accepted: list[dict] = []
    rejected: list[dict] = []

    for rec in records:
        reject_reason: Optional[str] = None

        for field in REQUIRED_FIELDS:
            if field not in rec or rec[field] is None:
                reject_reason = f"missing/null required field '{field}'"
                logger.warning(
                    "Rejecting fact id=%s: %s", rec.get("id", "?"), reject_reason
                )
                break

        if reject_reason is None and rec.get("id") in sane_bounds:
            lo, hi = sane_bounds[rec["id"]]
            val = rec.get("value")
            if isinstance(val, (int, float)) and not (lo <= val <= hi):
                reject_reason = (
                    f"sane_bounds violated: field=value observed={val} bounds=[{lo}, {hi}]"
                )
                logger.warning(
                    "Rejecting fact id=%s: %s", rec["id"], reject_reason
                )

        if reject_reason:
            rejected.append(rec)
        else:
            accepted.append(rec)

    return accepted, rejected


def write_facts(records: list[dict], output_path: str) -> None:
    """Atomically write the facts JSON array to output_path."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, indent=2, default=str))
    tmp.replace(out)


def check_facts_freshness(
    facts: list[dict],
    today: Optional[datetime.date] = None,
) -> list[str]:
    """
    Return a list of fact IDs whose data is stale (age > max_age_days).

    Used by the CI schema-contract step and the daily freshness probe (issue 22).
    A fact is stale when (today - as_of).days > max_age_days, except current
    tax-year statutory facts remain valid through their stated tax year.
    """
    if today is None:
        today = datetime.date.today()
    stale: list[str] = []
    for f in facts:
        try:
            as_of = datetime.date.fromisoformat(f["as_of"])
            max_age = int(f["max_age_days"])
            if (today - as_of).days > max_age and not is_current_tax_year_fact(f, today):
                stale.append(f.get("id", "?"))
        except (KeyError, ValueError, TypeError):
            pass
    return stale


def is_current_tax_year_fact(fact: dict, today: datetime.date) -> bool:
    """Return True when a statutory fact belongs to the current tax year."""
    try:
        return int(fact.get("tax_year")) == today.year
    except (TypeError, ValueError):
        return False
