"""Tests for adapting existing Finnhub news JSON into catalyst candidates."""

import sys
from pathlib import Path


DAILYNEWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DAILYNEWS_DIR))

import finnhub_candidates  # noqa: E402


SAMPLE_TOP_NEWS = {
    "metadata": {"type": "top_market_news"},
    "articles": [
        {
            "headline": "Fed signals patience",
            "summary": "Officials say they will wait for more data.",
            "source": "Bloomberg",
            "url": "https://www.bloomberg.com/news/articles/abc",
            "category": "top news",
            "datetime": "2026-05-15T20:30:00",
            "timestamp": 1779999000,
            "id": 1,
        },
        {
            "headline": "Tech leads markets higher",
            "summary": "QQQ closed at session highs.",
            "source": "CNBC",
            "url": "https://www.cnbc.com/2026/05/15/x.html",
            "category": "top news",
            "datetime": "2026-05-15T20:10:00",
            "timestamp": 1779998000,
            "id": 2,
        },
    ],
}


def test_to_candidates_maps_finnhub_articles_to_catalyst_shape():
    candidates = finnhub_candidates.to_candidates(
        SAMPLE_TOP_NEWS, category="market_news"
    )

    assert len(candidates) == 2
    first = candidates[0]
    assert first["title"] == "Fed signals patience"
    assert first["source"] == "Bloomberg"
    assert first["url"].startswith("https://www.bloomberg.com/")
    assert first["category"] == "market_news"
    assert first["why_it_matters"] == "Officials say they will wait for more data."
    assert first["published_at"].startswith("2026-05-15")
    assert first["relevance_score"] == 0.0


def test_to_candidates_skips_articles_missing_required_fields():
    payload = {
        "articles": [
            {"headline": None, "url": "https://x", "datetime": "2026-05-15T20:30:00"},
            {"headline": "No url", "datetime": "2026-05-15T20:30:00"},
            {"headline": "No date", "url": "https://y"},
            {
                "headline": "Good",
                "source": "Bloomberg",
                "url": "https://www.bloomberg.com/y",
                "datetime": "2026-05-15T20:30:00",
            },
        ]
    }

    candidates = finnhub_candidates.to_candidates(payload, category="market_news")

    assert [c["title"] for c in candidates] == ["Good"]
