"""End-to-end Market Catalysts collector.

Reads Finnhub `top_news.json` / `sector_news.json` from disk, pulls Phase 2a
official-source RSS feeds, normalizes everything into catalyst-candidate
shape, deduplicates by URL (keeping the higher-tier copy), and writes a
ranked ``market_catalysts.json``.

This runs in `deanfi-collectors`. The optional low-token AI ranker lives
downstream in `deanfi-data`.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import build_catalysts
import finnhub_candidates
import rss_candidates


SOURCE_TIER_ORDER = {"official": 3, "premium": 2, "standard": 1}

# Tracking query-string parameters that vary between sources but identify the
# same article. Drop them before dedup-keying so RSS-vs-Finnhub variants of
# the same URL collapse into one candidate.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand", "utm_social", "utm_social-type",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "yclid",
    "icid", "cmpid", "ncid", "cid", "source", "ref", "ref_src",
})


def _normalize_url(url: str) -> str:
    """Canonicalize a URL for dedup.

    Lowercases scheme + host, strips ``www.``, drops the fragment, removes
    common ad/tracking query params, and trims a single trailing slash off
    the path. Falls back to the stripped original on parse failure.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _dedupe_by_url(candidates: List[dict]) -> List[dict]:
    best: dict[str, dict] = {}
    for candidate in candidates:
        url = (candidate.get("url") or "").strip()
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        key = _normalize_url(url)
        if not key:
            continue
        tier = candidate.get("source_tier") or build_catalysts.classify_source_tier(candidate)
        candidate["source_tier"] = tier
        existing = best.get(key)
        if existing is None:
            best[key] = candidate
            continue
        if SOURCE_TIER_ORDER.get(tier, 0) > SOURCE_TIER_ORDER.get(existing["source_tier"], 0):
            best[key] = candidate
    return list(best.values())


def run(
    *,
    top_news_path: Path,
    sector_news_path: Path,
    output_path: Path,
    market_date: str,
    generated_at: str,
    weekly_mode: bool,
    fetcher: Callable[..., str] | None = None,
    rss_sources: tuple | None = None,
) -> dict:
    sources = rss_sources if rss_sources is not None else rss_candidates.OFFICIAL_FEEDS

    rss_items = rss_candidates.fetch_official_feeds(sources, fetcher=fetcher)
    finnhub_items: List[dict] = []
    finnhub_items.extend(
        finnhub_candidates.to_candidates(_load_json(top_news_path), category="market_news")
    )
    finnhub_items.extend(
        finnhub_candidates.to_candidates(_load_json(sector_news_path), category="sector_news")
    )

    deduped = _dedupe_by_url(rss_items + finnhub_items)

    payload = build_catalysts.build_market_catalysts(
        candidates=deduped,
        market_date=market_date,
        generated_at=generated_at,
        weekly_mode=weekly_mode,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    return payload


def _detect_weekly_mode(market_date: str | None) -> bool:
    if os.getenv("MARKET_PULSE_WEEKLY_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if not market_date:
        return False
    try:
        d = datetime.fromisoformat(market_date)
    except ValueError:
        return False
    # Monday is 0, Friday is 4.
    return d.weekday() == 4


def main() -> None:  # pragma: no cover - CLI entry point
    parser = argparse.ArgumentParser(description="Build deanfi market_catalysts.json")
    parser.add_argument("--top-news", required=True)
    parser.add_argument("--sector-news", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--market-date", required=True)
    args = parser.parse_args()

    generated_at = datetime.now(timezone.utc).isoformat()
    weekly_mode = _detect_weekly_mode(args.market_date)
    run(
        top_news_path=Path(args.top_news),
        sector_news_path=Path(args.sector_news),
        output_path=Path(args.output),
        market_date=args.market_date,
        generated_at=generated_at,
        weekly_mode=weekly_mode,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
