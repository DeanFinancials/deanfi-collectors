"""
GSC topics collector — entry point.

Usage:
    python -m gsctopics.run_gsc_topics <output_path> [--config <config_path>]

On source failure the existing topics.json is left intact and the process exits
with code 1 (last-good preservation, AC4).
"""
import argparse
import logging
import sys

from .fetch_gsc import fetch_gsc_topics
from .gsc_topics_utils import SourceFetchError, load_config, validate_topics, write_topics

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run(output_path: str, config_path: str = None) -> None:
    config = load_config(config_path)

    try:
        topics = fetch_gsc_topics(config)
    except SourceFetchError as exc:
        logger.error("GSC topics fetch failed — NOT writing output; last-good preserved: %s", exc)
        sys.exit(1)

    accepted, _ = validate_topics(topics)
    if not accepted:
        logger.error("No valid topic entries produced — NOT writing output; last-good preserved")
        sys.exit(1)

    write_topics(accepted, output_path)
    logger.info("Wrote %d topic entries to %s", len(accepted), output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch GSC topic opportunities")
    parser.add_argument("output", help="Path to write topics.json")
    parser.add_argument("--config", help="Path to config.yml (optional)")
    args = parser.parse_args()
    run(args.output, config_path=args.config)
