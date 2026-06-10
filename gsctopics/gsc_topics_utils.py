"""
Shared utilities for the GSC topics collector.

Provides schema constants, validation, slug generation, category assignment,
opportunity scoring, atomic file write, and config loading.
"""
import datetime
import json
import logging
import os
import re

import yaml

logger = logging.getLogger(__name__)

REQUIRED_TOPIC_FIELDS = frozenset({"slug", "category", "target_keyword", "added_at", "status"})
CATEGORY_ENUM = frozenset({"market-education", "retirement", "debt", "financial-tips"})
STATUS_ENUM = frozenset({"suggested", "consumed"})

# Keyword patterns per category; matched against lowercased, space-padded keyword.
# "market-education" is the fallback for anything that doesn't match.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "retirement": [
        "retire", "401k", "401 k", " ira ", "roth ira", "roth 401",
        "pension", "social security", "medicare", "required minimum distribution",
        " rmd ", "full retirement age",
    ],
    "debt": [
        "mortgage", "refinanc", "home equity", "heloc", "student loan",
        "student debt", "car loan", "auto loan", " debt ", "credit card debt",
        "credit score", " apr ", "debt payoff", "debt consolidat",
    ],
    "financial-tips": [
        "tax deduction", "tax bracket", "standard deduction", "tax return",
        "withholding", " hsa ", "hsa limit", " fsa ", " 529 ",
        "budget", "emergency fund", "net worth", "itemize",
    ],
}


class SourceFetchError(RuntimeError):
    pass


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def assign_category(keyword: str) -> str:
    padded = f" {keyword.lower()} "
    for category, patterns in _CATEGORY_KEYWORDS.items():
        if any(p in padded for p in patterns):
            return category
    return "market-education"


def opportunity_score(impressions: float, position: float) -> float:
    """Higher impressions at worse (higher) position = more latent opportunity."""
    return impressions / max(position, 1.0)


def validate_topics(topics: list) -> tuple:
    """
    Return (accepted, rejected).

    Required top-level fields: slug, category, target_keyword, added_at, status.
    GSC entries (source=="gsc") with a non-null gsc_evidence must have the four
    sub-fields: impressions, avg_position, clicks, window.
    Seed entries (source=="wes") may have gsc_evidence=None.
    """
    accepted, rejected = [], []
    for t in topics:
        reasons = []
        for f in REQUIRED_TOPIC_FIELDS:
            if f not in t or t[f] is None:
                reasons.append(f"missing required field '{f}'")
        category = t.get("category")
        if category is not None and category not in CATEGORY_ENUM:
            reasons.append(f"invalid category '{category}'")
        status = t.get("status")
        if status is not None and status not in STATUS_ENUM:
            reasons.append(f"invalid status '{status}'")
        ge = t.get("gsc_evidence")
        if ge is not None:
            for sf in ("impressions", "avg_position", "clicks", "window"):
                if sf not in ge:
                    reasons.append(f"gsc_evidence missing sub-field '{sf}'")
        if reasons:
            logger.warning("Rejecting topic slug=%s: %s", t.get("slug", "?"), "; ".join(reasons))
            rejected.append(t)
        else:
            accepted.append(t)
    return accepted, rejected


def write_topics(topics: list, output_path: str) -> None:
    tmp = output_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(topics, f, indent=2)
    os.replace(tmp, output_path)


def check_topics_freshness(
    topics: list,
    threshold_days: int = 14,
    today: datetime.date = None,
) -> bool:
    """
    Return True if the newest non-consumed entry's added_at is within threshold_days.

    Returns False (stale) when the newest non-consumed added_at > threshold_days ago.
    Used by the CI schema-contract step and the daily freshness probe (issue 22).
    An empty non-consumed list is treated as fresh (no entries to check).
    """
    if today is None:
        today = datetime.date.today()
    non_consumed = [t for t in topics if t.get("status") != "consumed"]
    if not non_consumed:
        return True
    dates = []
    for t in non_consumed:
        added_at = t.get("added_at")
        if added_at:
            try:
                dates.append(datetime.date.fromisoformat(added_at))
            except ValueError:
                pass
    if not dates:
        return True
    newest = max(dates)
    return (today - newest).days <= threshold_days


def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    with open(config_path) as f:
        return yaml.safe_load(f)
