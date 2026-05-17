"""Parse RSS 2.0 feeds into normalized catalyst-candidate dicts.

Network fetching is intentionally separated from parsing so the parser stays
unit-testable against XML fixtures.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, List
from xml.etree import ElementTree as ET


# Phase 2 RSS feed catalog. Each entry is (name, category, url).
OFFICIAL_FEEDS: tuple[dict, ...] = (
    {
        "name": "Federal Reserve",
        "category": "monetary_policy",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
    },
    {
        "name": "BLS",
        "category": "labor_inflation",
        "url": "https://www.bls.gov/feed/news_release/empsit.rss",
    },
    {
        "name": "BEA",
        "category": "growth_output",
        "url": "https://apps.bea.gov/rss/rss.xml",
    },
    {
        "name": "Treasury",
        "category": "fiscal_policy",
        "url": "https://home.treasury.gov/news/press-releases/feed",
    },
)


Fetcher = Callable[..., str]


def _default_fetcher(url: str, *, timeout: int = 15) -> str:  # pragma: no cover
    import requests

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    text = elem.text.strip()
    return text or None


def _to_iso(pub_date: str | None) -> str | None:
    if not pub_date:
        return None
    try:
        dt = parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt.isoformat()


def parse_rss(xml_text: str, *, source: str, category: str) -> List[dict]:
    """Parse an RSS 2.0 document into catalyst candidates.

    Skips items missing any of: ``title``, ``link``, ``pubDate``.
    """
    root = ET.fromstring(xml_text)
    candidates: List[dict] = []
    for item in root.iter("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        pub_date = _text(item.find("pubDate"))
        published_at = _to_iso(pub_date)
        if not (title and link and published_at):
            continue
        description = _text(item.find("description")) or ""
        candidates.append(
            {
                "title": title,
                "source": source,
                "url": link,
                "published_at": published_at,
                "category": category,
                "relevance_score": 0.0,
                "why_it_matters": description,
            }
        )
    return candidates


def _default_log(message: str) -> None:
    """Print to stdout so GitHub Actions captures the message in workflow logs."""
    print(message)


def fetch_official_feeds(
    sources: Iterable[dict],
    *,
    fetcher: Fetcher | None = None,
    timeout: int = 15,
    log: Callable[[str], None] | None = None,
) -> List[dict]:
    """Fetch + parse a list of RSS sources, swallowing individual failures.

    ``sources`` items must have ``name``, ``category``, and ``url``.
    ``fetcher`` is injected for testability; defaults to ``requests.get``.

    Per-feed failures are logged but never raised. ``log`` defaults to
    :func:`_default_log` (prints to stdout, which GitHub Actions captures)
    so a persistently broken feed surfaces in workflow logs instead of
    silently degrading official-source coverage. Tests can pass ``log=lambda
    msg: None`` to suppress output.
    """
    do_fetch = fetcher or _default_fetcher
    do_log = log if log is not None else _default_log
    out: List[dict] = []
    attempted = 0
    failures = 0
    for source in sources:
        attempted += 1
        url = source["url"]
        try:
            xml_text = do_fetch(url, timeout=timeout)
            out.extend(parse_rss(xml_text, source=source["name"], category=source["category"]))
        except Exception as exc:  # noqa: BLE001 — feed failures must not break collection
            failures += 1
            do_log(f"RSS feed failed: {source['name']} ({url}) — {exc!r}")
            continue
    if failures:
        do_log(f"RSS feed summary: {failures}/{attempted} feeds failed (parsed {len(out)} items overall)")
    return out
