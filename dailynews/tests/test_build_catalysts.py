"""Tests for deterministic catalyst assembly (Phase 2)."""

import json
import sys
from pathlib import Path


DAILYNEWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DAILYNEWS_DIR))

import build_catalysts  # noqa: E402


def test_schema_declares_required_top_level_sections():
    schema_path = DAILYNEWS_DIR / "market_catalysts.schema.json"
    schema = json.loads(schema_path.read_text())

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "DeanFi Market Catalysts"
    assert set(schema["required"]) == {"metadata", "ranked"}
    item_schema = schema["properties"]["ranked"]["items"]
    assert set(item_schema["required"]) >= {
        "title",
        "source",
        "url",
        "published_at",
        "category",
        "relevance_score",
        "why_it_matters",
    }


def test_build_market_catalysts_writes_required_metadata_and_empty_ranked_list_when_no_candidates():
    output = build_catalysts.build_market_catalysts(
        candidates=[],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    assert output["metadata"]["market_date"] == "2026-05-15"
    assert output["metadata"]["generated_at"] == "2026-05-15T21:05:00Z"
    assert output["metadata"]["weekly_mode"] is False
    assert output["metadata"]["expected_min_catalysts"] == 3
    assert output["metadata"]["ranking_method"] == "deterministic"
    assert output["ranked"] == []


def test_build_market_catalysts_expects_five_when_weekly_mode_is_on():
    output = build_catalysts.build_market_catalysts(
        candidates=[],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=True,
    )

    assert output["metadata"]["weekly_mode"] is True
    assert output["metadata"]["expected_min_catalysts"] == 5


def test_build_market_catalysts_tags_official_sources_by_domain():
    candidate = {
        "title": "FOMC statement",
        "source": "Federal Reserve",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260515a.htm",
        "published_at": "2026-05-15T18:00:00Z",
        "category": "monetary_policy",
        "relevance_score": 0.0,
        "why_it_matters": "",
    }

    output = build_catalysts.build_market_catalysts(
        candidates=[candidate],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    assert output["ranked"][0]["source_tier"] == "official"


def test_build_market_catalysts_tags_premium_and_standard_tiers():
    bloomberg = {
        "title": "Markets close mixed",
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com/news/articles/abc",
        "published_at": "2026-05-15T20:30:00Z",
        "category": "markets",
        "relevance_score": 0.0,
        "why_it_matters": "",
    }
    seeking_alpha = {
        "title": "Sector rotation continues",
        "source": "SeekingAlpha",
        "url": "https://seekingalpha.com/news/xyz",
        "published_at": "2026-05-15T19:00:00Z",
        "category": "markets",
        "relevance_score": 0.0,
        "why_it_matters": "",
    }

    output = build_catalysts.build_market_catalysts(
        candidates=[bloomberg, seeking_alpha],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    by_source = {c["source"]: c for c in output["ranked"]}
    assert by_source["Bloomberg"]["source_tier"] == "premium"
    assert by_source["SeekingAlpha"]["source_tier"] == "standard"


def test_official_catalyst_outranks_premium_outranks_standard_on_same_day():
    common = {
        "published_at": "2026-05-15T18:00:00Z",
        "category": "markets",
        "why_it_matters": "",
        "relevance_score": 0.0,
    }
    candidates = [
        {**common, "title": "Sector rotation", "source": "SeekingAlpha",
         "url": "https://seekingalpha.com/news/1"},
        {**common, "title": "Markets recap", "source": "Bloomberg",
         "url": "https://www.bloomberg.com/news/articles/2"},
        {**common, "title": "FOMC decision", "source": "Federal Reserve",
         "url": "https://www.federalreserve.gov/newsevents/pressreleases/3.htm"},
    ]

    output = build_catalysts.build_market_catalysts(
        candidates=candidates,
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    titles_in_order = [c["title"] for c in output["ranked"]]
    assert titles_in_order == ["FOMC decision", "Markets recap", "Sector rotation"]
    scores = [c["relevance_score"] for c in output["ranked"]]
    assert scores == sorted(scores, reverse=True)


def test_more_recent_catalyst_outranks_older_catalyst_at_same_tier():
    common = {
        "title": "Headline",
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com/news/x",
        "category": "markets",
        "why_it_matters": "",
        "relevance_score": 0.0,
    }
    older = {**common, "title": "Older", "published_at": "2026-05-15T13:00:00Z"}
    newer = {**common, "title": "Newer", "published_at": "2026-05-15T20:30:00Z"}

    output = build_catalysts.build_market_catalysts(
        candidates=[older, newer],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    assert [c["title"] for c in output["ranked"]] == ["Newer", "Older"]


def test_topic_match_boosts_score_when_topics_provided():
    common = {
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com/news/x",
        "published_at": "2026-05-15T19:00:00Z",
        "category": "markets",
        "why_it_matters": "",
        "relevance_score": 0.0,
    }
    on_topic = {**common, "title": "Fed signals rate path", "url": "https://www.bloomberg.com/a"}
    off_topic = {**common, "title": "Cricket league launches", "url": "https://www.bloomberg.com/b"}

    output = build_catalysts.build_market_catalysts(
        candidates=[off_topic, on_topic],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
        topics=["rate", "fed"],
    )

    assert [c["title"] for c in output["ranked"]][0] == "Fed signals rate path"


def test_topic_match_is_case_insensitive_and_substring_safe():
    bonus = build_catalysts.compute_topic_bonus(
        {"title": "CPI prints hotter than expected", "why_it_matters": ""},
        topics=["cpi", "inflation"],
    )
    no_bonus = build_catalysts.compute_topic_bonus(
        {"title": "Crypto firm files for IPO", "why_it_matters": ""},
        topics=["cpi", "inflation"],
    )
    assert bonus > 0
    assert no_bonus == 0.0


def test_topic_match_does_not_match_inside_larger_words():
    bonus = build_catalysts.compute_topic_bonus(
        {"title": "Rate expectations move yields", "why_it_matters": ""},
        topics=["rate"],
    )
    no_bonus = build_catalysts.compute_topic_bonus(
        {"title": "Corporate earnings calendar expands", "why_it_matters": ""},
        topics=["rate"],
    )
    assert bonus > 0
    assert no_bonus == 0.0
