"""
Shared utilities for the education-facts collector.

Provides: retry-with-backoff HTTP fetch, record validation (required fields,
category, value type, as_of date, sane bounds), facts JSON writer, and config loader.
"""
import datetime
import json
import logging
import math
import re
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


# as_of must be an ISO calendar date (YYYY-MM-DD) naming a real day. The
# website's freshness probe parses it with JavaScript `new Date()`, which accepts
# every such string; requiring this strict subset keeps "" and other
# unparseable values out of facts.json.
_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A fact's value is a finite number, except facts in TEXT_UNIT, whose value is a
# non-empty display string (e.g. "67 years").
TEXT_UNIT = "text"


def _invalid_field_reason(rec: dict) -> Optional[str]:
    """Return why rec breaks the facts.json contract, or None when it is valid."""
    for field in REQUIRED_FIELDS:
        if field not in rec or rec[field] is None:
            return f"missing/null required field '{field}'"

    if rec["category"] not in CATEGORY_ENUM:
        return f"invalid category '{rec['category']}'"

    value = rec["value"]
    if rec["unit"] == TEXT_UNIT:
        if not isinstance(value, str) or not value.strip():
            return f"text fact value must be a non-empty string, got {value!r}"
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return f"value must be a finite number, got {value!r}"

    as_of = rec["as_of"]
    try:
        if not isinstance(as_of, str) or not _AS_OF_RE.match(as_of):
            raise ValueError
        datetime.date.fromisoformat(as_of)
    except ValueError:
        return f"as_of must be a YYYY-MM-DD date, got {as_of!r}"

    return None


def validate_records(
    records: list[dict],
    sane_bounds: Optional[dict] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Split records into (accepted, rejected).

    A record is rejected if any required field is absent/null, its category is
    outside CATEGORY_ENUM, its value is not a finite number (or, for unit
    "text", a non-empty string), its as_of is not a real YYYY-MM-DD date, or its
    numeric value falls outside the configured sane bounds.  Rejected records
    are logged with the reason and observed value so CI output is auditable.
    """
    sane_bounds = sane_bounds or {}
    accepted: list[dict] = []
    rejected: list[dict] = []

    for rec in records:
        reject_reason = _invalid_field_reason(rec)

        if reject_reason is None and rec.get("id") in sane_bounds:
            lo, hi = sane_bounds[rec["id"]]
            val = rec.get("value")
            if isinstance(val, (int, float)) and not (lo <= val <= hi):
                reject_reason = (
                    f"sane_bounds violated: field=value observed={val} bounds=[{lo}, {hi}]"
                )

        if reject_reason:
            logger.warning("Rejecting fact id=%s: %s", rec.get("id", "?"), reject_reason)
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


def is_current_tax_year_fact(fact: dict, today: datetime.date) -> bool:
    """Return True when a statutory fact belongs to the current tax year."""
    try:
        return int(fact.get("tax_year")) == today.year
    except (TypeError, ValueError):
        return False
