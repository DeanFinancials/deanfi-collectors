"""Deterministic catalyst assembly for Market Pulse.

Inputs are candidate news items (from RSS feeds, Finnhub, etc.) already
normalized into the catalyst shape. This module is responsible for:

- assembling the wrapping ``market_catalysts.json`` payload
- (later) deterministic scoring + ranking
- (later) tagging official-source items

The optional low-token AI ranker lives in ``deanfi-data``, not here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse


OFFICIAL_DOMAINS = {
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "treasury.gov",
}

PREMIUM_SOURCES = {
    "Bloomberg",
    "CNBC",
    "MarketWatch",
    "Reuters",
    "WSJ",
    "Wall Street Journal",
    "Financial Times",
    "FT",
}


def expected_min_catalysts(weekly_mode: bool) -> int:
    """Return the publish-gate minimum for ranked catalysts."""
    return 5 if weekly_mode else 3


SOURCE_TIER_WEIGHT = {"official": 60.0, "premium": 30.0, "standard": 10.0}

# Baseline topics for the deterministic relevance score. The downstream
# `deanfi-data` consumer can override or extend with same-day market context
# (e.g. leader/laggard sectors, major tickers) before AI ranking.
BASELINE_TOPICS: tuple[str, ...] = (
    "fed",
    "fomc",
    "rate",
    "rates",
    "inflation",
    "cpi",
    "ppi",
    "pce",
    "gdp",
    "jobs",
    "payrolls",
    "unemployment",
    "earnings",
    "guidance",
    "treasury",
    "yield",
    "oil",
    "vix",
    "s&p",
    "nasdaq",
    "dow",
)


def compute_topic_bonus(candidate: dict, *, topics: Iterable[str]) -> float:
    """Return 0–20 points based on how many distinct topics the candidate matches."""
    haystack = " ".join(
        [
            (candidate.get("title") or ""),
            (candidate.get("why_it_matters") or ""),
        ]
    ).lower()
    if not haystack.strip():
        return 0.0
    seen: set[str] = set()
    for topic in topics:
        needle = (topic or "").strip().lower()
        if not needle or needle in seen:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            seen.add(needle)
    if not seen:
        return 0.0
    # 5 points per matched topic, capped at 20.
    return float(min(20, 5 * len(seen)))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_relevance_score(
    candidate: dict,
    *,
    now: datetime | None = None,
    topics: Iterable[str] | None = None,
) -> float:
    """Deterministic relevance score combining source tier + recency.

    Future slices will add topic relevance and same-day market-move linkage.
    """
    tier = candidate.get("source_tier") or classify_source_tier(candidate)
    score = SOURCE_TIER_WEIGHT.get(tier, 0.0)

    published = _parse_ts(candidate.get("published_at"))
    reference = now or datetime.now(timezone.utc)
    if published is not None:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (reference - published).total_seconds() / 3600.0)
        # Up to 30 points for recency, decaying over 48h.
        recency = max(0.0, 30.0 - (age_hours * (30.0 / 48.0)))
        score += recency

    score += compute_topic_bonus(candidate, topics=topics or BASELINE_TOPICS)
    return round(score, 4)


def classify_source_tier(candidate: dict) -> str:
    """Tag a candidate as ``official`` / ``premium`` / ``standard`` by domain+source."""
    url = candidate.get("url") or ""
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    for official in OFFICIAL_DOMAINS:
        if host == official or host.endswith("." + official):
            return "official"
    if (candidate.get("source") or "") in PREMIUM_SOURCES:
        return "premium"
    return "standard"


def _non_empty_or_fallback(value: object, fallback: object) -> str:
    text = str(value or "").strip()
    if text:
        return text
    return str(fallback or "").strip()


def build_market_catalysts(
    *,
    candidates: Iterable[dict],
    market_date: str | None,
    generated_at: str,
    weekly_mode: bool,
    topics: Iterable[str] | None = None,
) -> dict:
    """Assemble the ``market_catalysts.json`` payload from candidates.

    Phase 2 first slice: no scoring yet. Candidates pass through unchanged.
    Subsequent slices add deterministic scoring and official-source tagging.
    """
    now = _parse_ts(generated_at) or datetime.now(timezone.utc)
    scored = []
    for candidate in candidates:
        tagged = dict(candidate)
        tagged["why_it_matters"] = _non_empty_or_fallback(
            tagged.get("why_it_matters"),
            tagged.get("title"),
        )
        tagged["source_tier"] = tagged.get("source_tier") or classify_source_tier(tagged)
        tagged["relevance_score"] = compute_relevance_score(tagged, now=now, topics=topics)
        scored.append(tagged)
    scored.sort(key=lambda c: c["relevance_score"], reverse=True)

    return {
        "metadata": {
            "market_date": market_date,
            "generated_at": generated_at,
            "weekly_mode": weekly_mode,
            "expected_min_catalysts": expected_min_catalysts(weekly_mode),
            "ranking_method": "deterministic",
        },
        "ranked": scored,
    }
