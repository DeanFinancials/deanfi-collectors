"""
Education-facts collector entry point.

Calls all three source groups, merges results, validates records, and writes
education/facts.json.  Any SourceFetchError from a group keeps the last-good
output file unchanged and exits non-zero (AC2).

Usage (from deanfi-collectors root):
    python -m educationfacts.run_education_facts --output ./educationfacts/facts.json

CI workflow copies the output to data-cache/education/facts.json after success.
"""
import argparse
import logging
import sys
from pathlib import Path

from .education_facts_utils import SourceFetchError, load_config, validate_records, write_facts
from .fetch_group1 import fetch_group1
from .fetch_group2 import fetch_group2
from .fetch_group3 import fetch_group3 as _fetch_group3


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_group3(config: dict) -> list:
    return _fetch_group3(config)


def run(output_path: str, config_path: str | None = None) -> None:
    """
    Execute the full collection pipeline.

    Raises SystemExit(1) if:
      - any source group raises SourceFetchError (keeps last-good file)
      - zero valid records remain after validation
    """
    config = load_config(config_path)
    sane_bounds = config.get("sane_bounds", {})

    groups = [
        ("group1", lambda: fetch_group1(config)),
        ("group2", lambda: fetch_group2(config)),
        ("group3", lambda: fetch_group3(config)),
    ]

    all_records: list[dict] = []
    failed_groups: list[str] = []

    for group_name, fetch_fn in groups:
        try:
            records = fetch_fn()
            all_records.extend(records)
            logger.info("%s: collected %d records", group_name, len(records))
        except SourceFetchError as exc:
            logger.error("%s failed: %s", group_name, exc)
            failed_groups.append(group_name)

    if failed_groups:
        logger.error(
            "One or more source groups failed (%s) — NOT writing output; last-good preserved",
            ", ".join(failed_groups),
        )
        sys.exit(1)

    accepted, rejected = validate_records(all_records, sane_bounds)
    logger.info(
        "Validation: %d accepted, %d rejected", len(accepted), len(rejected)
    )

    if not accepted:
        logger.error("Zero valid records produced — NOT writing output")
        sys.exit(1)

    write_facts(accepted, output_path)
    logger.info("Wrote %d facts to %s", len(accepted), output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect education facts and write facts.json")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "facts.json"),
        help="Output path for facts.json",
    )
    parser.add_argument("--config", default=None, help="Path to config.yml (default: built-in)")
    args = parser.parse_args()
    run(output_path=args.output, config_path=args.config)


if __name__ == "__main__":
    main()
