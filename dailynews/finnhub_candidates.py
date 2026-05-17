"""Adapt existing Finnhub news payloads (top_news.json / sector_news.json) into
catalyst-candidate dicts. No network access here — feeds the same shape that
``rss_candidates.parse_rss`` produces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List


def _normalize_datetime(value) -> str | None:
    # Finnhub's `datetime` is a UTC epoch second; the string-typed fallback
    # path (used when callers pre-format) is also UTC by convention. A naive
    # ISO string here will flow through without an offset, and downstream
    # `compute_relevance_score` treats unaware datetimes as UTC.
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            return None
    return None


def to_candidates(payload: dict, *, category: str) -> List[dict]:
    """Convert a Finnhub-style ``{articles: [...]}`` payload into candidates."""
    articles = (payload or {}).get("articles") or []
    out: List[dict] = []
    for article in articles:
        title = article.get("headline")
        url = article.get("url")
        published_at = _normalize_datetime(article.get("datetime")) or _normalize_datetime(
            article.get("timestamp")
        )
        if not (title and url and published_at):
            continue
        out.append(
            {
                "title": title,
                "source": article.get("source") or "Unknown",
                "url": url,
                "published_at": published_at,
                "category": category,
                "relevance_score": 0.0,
                "why_it_matters": article.get("summary") or "",
            }
        )
    return out
