"""Tests for the deanfi-collectors catalyst collection entry point."""

import json
import sys
from pathlib import Path


DAILYNEWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DAILYNEWS_DIR))

import collect_catalysts  # noqa: E402


def test_collect_catalysts_merges_rss_and_finnhub_into_market_catalysts_json(tmp_path):
    top_news = tmp_path / "top_news.json"
    top_news.write_text(json.dumps({
        "articles": [
            {
                "headline": "Tech leads",
                "source": "CNBC",
                "url": "https://www.cnbc.com/x",
                "datetime": "2026-05-15T20:10:00",
            }
        ]
    }))
    sector_news = tmp_path / "sector_news.json"
    sector_news.write_text(json.dumps({"articles": []}))

    rss_fixture = (
        "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
        "<item><title>FOMC statement</title>"
        "<link>https://www.federalreserve.gov/newsevents/pressreleases/a.htm</link>"
        "<pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )

    def fake_fetch(url, *, timeout):
        return rss_fixture

    output_path = tmp_path / "market_catalysts.json"
    collect_catalysts.run(
        top_news_path=top_news,
        sector_news_path=sector_news,
        output_path=output_path,
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
        fetcher=fake_fetch,
    )

    payload = json.loads(output_path.read_text())
    assert payload["metadata"]["market_date"] == "2026-05-15"
    assert payload["metadata"]["expected_min_catalysts"] == 3
    titles = [c["title"] for c in payload["ranked"]]
    assert "FOMC statement" in titles
    assert "Tech leads" in titles
    # Official source must outrank a same-day standard one.
    assert titles[0] == "FOMC statement"


def test_collect_catalysts_deduplicates_by_url(tmp_path):
    top_news = tmp_path / "top_news.json"
    top_news.write_text(json.dumps({
        "articles": [
            {
                "headline": "FOMC statement",
                "source": "CNBC",
                "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
                "datetime": "2026-05-15T18:30:00",
            }
        ]
    }))
    sector_news = tmp_path / "sector_news.json"
    sector_news.write_text(json.dumps({"articles": []}))

    rss_fixture = (
        "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
        "<item><title>FOMC statement</title>"
        "<link>https://www.federalreserve.gov/newsevents/pressreleases/a.htm</link>"
        "<pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )

    def fake_fetch(url, *, timeout):
        return rss_fixture

    output_path = tmp_path / "market_catalysts.json"
    collect_catalysts.run(
        top_news_path=top_news,
        sector_news_path=sector_news,
        output_path=output_path,
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
        fetcher=fake_fetch,
    )

    payload = json.loads(output_path.read_text())
    urls = [c["url"] for c in payload["ranked"]]
    assert urls.count("https://www.federalreserve.gov/newsevents/pressreleases/a.htm") == 1
    # The official-tier copy should be the one that survives dedupe.
    fed = payload["ranked"][0]
    assert fed["source"] == "Federal Reserve"


def test_normalize_url_collapses_divergent_forms():
    """`www.`, trailing slash, fragment, and tracking params must collapse to one key."""
    cases = [
        "https://www.bloomberg.com/news/article",
        "https://bloomberg.com/news/article/",
        "https://www.BLOOMBERG.com/news/article#section",
        "https://www.bloomberg.com/news/article?utm_source=rss&utm_medium=feed",
        "https://www.bloomberg.com/news/article?fbclid=123",
    ]
    keys = {collect_catalysts._normalize_url(u) for u in cases}
    assert len(keys) == 1, f"expected all forms to normalize to one key, got {keys}"


def test_normalize_url_preserves_non_tracking_query_params():
    """A meaningful query param (e.g. article id) must survive normalization."""
    a = collect_catalysts._normalize_url("https://example.com/x?id=42&utm_source=rss")
    b = collect_catalysts._normalize_url("https://example.com/x?id=42")
    c = collect_catalysts._normalize_url("https://example.com/x?id=99")
    assert a == b
    assert a != c


def test_collect_catalysts_deduplicates_across_normalized_url_forms(tmp_path):
    """RSS-vs-Finnhub URL variants for the same article must collapse to one catalyst."""
    top_news = tmp_path / "top_news.json"
    top_news.write_text(json.dumps({
        "articles": [
            {
                "headline": "FOMC statement",
                "source": "CNBC",
                # Tracking-param + www. variant from a syndicated feed.
                "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm?utm_source=rss",
                "datetime": "2026-05-15T18:30:00",
            }
        ]
    }))
    sector_news = tmp_path / "sector_news.json"
    sector_news.write_text(json.dumps({"articles": []}))

    rss_fixture = (
        "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
        "<item><title>FOMC statement</title>"
        # Bare-host + trailing-slash variant from the official feed.
        "<link>https://federalreserve.gov/newsevents/pressreleases/a.htm/</link>"
        "<pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )
    output_path = tmp_path / "market_catalysts.json"
    collect_catalysts.run(
        top_news_path=top_news,
        sector_news_path=sector_news,
        output_path=output_path,
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
        fetcher=lambda url, *, timeout: rss_fixture,
    )
    payload = json.loads(output_path.read_text())
    assert len(payload["ranked"]) == 1, payload["ranked"]
    # Official tier should win the dedup conflict.
    assert payload["ranked"][0]["source"] == "Federal Reserve"


def test_relative_urls_are_dropped(tmp_path):
    """Candidates with relative URLs must be excluded from the output."""
    top_news = tmp_path / "top_news.json"
    top_news.write_text(json.dumps({
        "articles": [
            {
                "headline": "Relative link article",
                "source": "Reuters",
                "url": "/markets/us/some-story-2026-05-18",
                "datetime": "2026-05-18T20:00:00",
            },
            {
                "headline": "Absolute link article",
                "source": "Reuters",
                "url": "https://reuters.com/markets/us/some-story-2026-05-18",
                "datetime": "2026-05-18T20:00:00",
            },
        ]
    }))
    sector_news = tmp_path / "sector_news.json"
    sector_news.write_text(json.dumps({"articles": []}))

    output_path = tmp_path / "market_catalysts.json"
    collect_catalysts.run(
        top_news_path=top_news,
        sector_news_path=sector_news,
        output_path=output_path,
        market_date="2026-05-18",
        generated_at="2026-05-18T21:05:00Z",
        weekly_mode=False,
        fetcher=lambda url, *, timeout: (
            "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel></channel></rss>"
        ),
    )

    payload = json.loads(output_path.read_text())
    urls = [c["url"] for c in payload["ranked"]]
    assert "/markets/us/some-story-2026-05-18" not in urls
    assert "https://reuters.com/markets/us/some-story-2026-05-18" in urls


def test_collected_payload_validates_against_schema(tmp_path):
    import jsonschema

    top_news = tmp_path / "top_news.json"
    top_news.write_text(json.dumps({
        "articles": [
            {
                "headline": "CNBC headline",
                "source": "CNBC",
                "url": "https://www.cnbc.com/x",
                "datetime": "2026-05-15T20:10:00",
                "summary": "details",
            }
        ]
    }))
    sector_news = tmp_path / "sector_news.json"
    sector_news.write_text(json.dumps({"articles": []}))

    rss_fixture = (
        "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
        "<item><title>FOMC statement</title>"
        "<link>https://www.federalreserve.gov/x.htm</link>"
        "<pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate>"
        "<description>statement</description>"
        "</item>"
        "</channel></rss>"
    )

    output_path = tmp_path / "market_catalysts.json"
    collect_catalysts.run(
        top_news_path=top_news,
        sector_news_path=sector_news,
        output_path=output_path,
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
        fetcher=lambda url, *, timeout: rss_fixture,
    )

    schema = json.loads((DAILYNEWS_DIR / "market_catalysts.schema.json").read_text())
    payload = json.loads(output_path.read_text())
    jsonschema.validate(payload, schema)
