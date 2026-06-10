"""
Group 3 — IRS / SSA / FSA seed facts.

These are annual statutory figures (contribution limits, COLA, loan rates) that
change at most once per year.  They are maintained as seed entries in config.yml
rather than fetched from HTML pages (which change layout annually).  The module:

  - Reads seed_facts from the config
  - Validates that each seed is within its max_age_days staleness threshold
  - Returns the complete list of accepted seeds as §7.11 fact records

No network calls are made by this group.  SourceFetchError is raised only if
the seed data is stale beyond its threshold (treats stale config as a "source
failure" that keeps last-good).
"""
import logging
from datetime import date, datetime

from .education_facts_utils import REQUIRED_FIELDS, SourceFetchError

logger = logging.getLogger(__name__)


def load_seed_facts(config: dict) -> list[dict]:
    """
    Read seed_facts from config, validate staleness, return accepted records.

    Raises SourceFetchError if any seed exceeds its max_age_days threshold.
    Seeds with non-numeric values (unit='text') are included without sane-bounds
    checking (that happens in run_education_facts.validate_records).
    """
    seeds: list[dict] = config.get("seed_facts", [])
    if not seeds:
        logger.warning("No seed_facts found in config")
        return []

    today = date.today()
    stale: list[str] = []
    accepted: list[dict] = []

    for raw in seeds:
        rec = dict(raw)  # shallow copy so we don't mutate config

        # Remove non-§7.11 fields that may appear in config for human readability
        # (tax_year is an optional §7.11 field — keep it)

        # Validate staleness
        max_age = rec.get("max_age_days", 400)
        as_of_str = rec.get("as_of", "")
        try:
            as_of_date = datetime.strptime(as_of_str, "%Y-%m-%d").date()
        except ValueError:
            logger.error(
                "Seed id=%s has unparseable as_of value '%s'", rec.get("id"), as_of_str
            )
            stale.append(rec.get("id", "?"))
            continue

        age_days = (today - as_of_date).days
        if age_days > max_age:
            logger.error(
                "Seed id=%s is %d days old, exceeds max_age_days=%d — update config.yml",
                rec.get("id"), age_days, max_age,
            )
            stale.append(rec.get("id", "?"))
            continue

        accepted.append(rec)

    if stale:
        raise SourceFetchError(
            f"Stale seed facts detected (update config.yml): {', '.join(stale)}"
        )

    return accepted


def fetch_group3(config: dict) -> list[dict]:
    """Return all Group 3 fact records (IRS / SSA / FSA seeds)."""
    return load_seed_facts(config)
