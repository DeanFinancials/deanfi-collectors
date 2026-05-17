"""Tests for RSS-derived catalyst candidates."""

import sys
import textwrap
from pathlib import Path


DAILYNEWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DAILYNEWS_DIR))

import rss_candidates  # noqa: E402


FED_FIXTURE = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Federal Reserve Board - All press releases</title>
        <link>https://www.federalreserve.gov</link>
        <description>Press releases</description>
        <item>
          <title>Federal Reserve issues FOMC statement</title>
          <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260515a.htm</link>
          <description>The Committee decided to maintain the target range.</description>
          <pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate>
          <guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260515a.htm</guid>
        </item>
        <item>
          <title>Beige Book released</title>
          <link>https://www.federalreserve.gov/monetarypolicy/beigebook202605.htm</link>
          <description>Summary of commentary on current economic conditions.</description>
          <pubDate>Wed, 15 May 2026 14:00:00 GMT</pubDate>
          <guid>https://www.federalreserve.gov/monetarypolicy/beigebook202605.htm</guid>
        </item>
      </channel>
    </rss>
    """
)


def test_parse_rss_returns_normalized_candidates():
    candidates = rss_candidates.parse_rss(
        FED_FIXTURE,
        source="Federal Reserve",
        category="monetary_policy",
    )

    assert len(candidates) == 2
    first = candidates[0]
    assert first["title"] == "Federal Reserve issues FOMC statement"
    assert first["source"] == "Federal Reserve"
    assert first["category"] == "monetary_policy"
    assert first["url"].startswith("https://www.federalreserve.gov/")
    assert first["published_at"] == "2026-05-15T18:00:00+00:00"
    assert "why_it_matters" in first
    assert "relevance_score" in first


def test_parse_rss_skips_items_missing_required_fields():
    broken = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Has title and link but no date</title>
              <link>https://www.federalreserve.gov/x.htm</link>
            </item>
            <item>
              <title>Missing link</title>
              <pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate>
            </item>
            <item>
              <title>Valid item</title>
              <link>https://www.federalreserve.gov/good.htm</link>
              <pubDate>Wed, 15 May 2026 18:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """
    )

    candidates = rss_candidates.parse_rss(
        broken,
        source="Federal Reserve",
        category="monetary_policy",
    )

    assert len(candidates) == 1
    assert candidates[0]["title"] == "Valid item"


def test_fetch_official_feeds_returns_combined_candidates_from_configured_sources():
    bls_xml = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Consumer Price Index - April 2026</title>
              <link>https://www.bls.gov/news.release/cpi.htm</link>
              <pubDate>Wed, 14 May 2026 12:30:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """
    )

    def fake_fetch(url: str, *, timeout: int) -> str:
        return {
            "https://www.federalreserve.gov/feeds/press_all.xml": FED_FIXTURE,
            "https://www.bls.gov/feed/news_release/empsit.rss": bls_xml,
        }[url]

    sources = [
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
    ]

    candidates = rss_candidates.fetch_official_feeds(sources, fetcher=fake_fetch)

    sources_in_output = {c["source"] for c in candidates}
    assert sources_in_output == {"Federal Reserve", "BLS"}
    assert any(c["category"] == "labor_inflation" for c in candidates)


def test_fetch_official_feeds_swallows_individual_feed_failures():
    def flaky_fetch(url: str, *, timeout: int) -> str:
        if "bls.gov" in url:
            raise RuntimeError("network down for BLS")
        return FED_FIXTURE

    sources = [
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
    ]

    candidates = rss_candidates.fetch_official_feeds(sources, fetcher=flaky_fetch)

    assert all(c["source"] == "Federal Reserve" for c in candidates)
    assert len(candidates) == 2
