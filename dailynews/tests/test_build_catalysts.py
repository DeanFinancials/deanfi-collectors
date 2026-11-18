"""Tests for deterministic catalyst assembly."""

import json
from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest


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


def test_build_market_catalysts_fills_missing_why_it_matters_from_title():
    candidate = {
        "title": "Tech leads markets higher",
        "source": "CNBC",
        "url": "https://www.cnbc.com/2026/05/15/x.html",
        "published_at": "2026-05-15T20:10:00Z",
        "category": "market_news",
        "relevance_score": 0.0,
        "why_it_matters": "",
    }

    output = build_catalysts.build_market_catalysts(
        candidates=[candidate],
        market_date="2026-05-15",
        generated_at="2026-05-15T21:05:00Z",
        weekly_mode=False,
    )

    assert output["ranked"][0]["why_it_matters"] == "Tech leads markets higher"


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


# Real 2026-11-17 headlines (deanfi-data daily-news/market_catalysts.json).
_GENERATED_2026_11_17 = "2026-11-18T03:45:09+00:00"
# (source, published_at, title[, why_it_matters]); Reuters items repeat the title.
_REAL_2026_11_17 = [
    ("Reuters", "2026-11-17T23:41:29", "Eisenkot-led bloc replaces Netanyahu ally as Knesset speaker - Reuters"),
    ("Reuters", "2026-11-17T23:15:00", "Bahrain says air defences intercepted Iranian attacks - Reuters"),
    ("Reuters", "2026-11-17T22:05:00", "Trump to meet Marcos in Manila before China talks - Reuters"),
    ("Reuters", "2026-11-17T13:19:22", "Angola central bank eases policy further as inflation keeps falling - Reuters"),
    ("Reuters", "2026-11-17T20:21:10", "Estonia's plan to shut Russian border disrupts families on both sides - Reuters"),
    ("Reuters", "2026-11-17T21:52:56", "Wall Street ends lower ahead of Nvidia results, focus turns to Anthropic debut - Reuters"),
    ("CNBC", "2026-11-17T16:42:21", "Jensen Huang breaks his silence ahead of Nvidia earnings — plus, 1 stock to buy on weakness",
     'The Investing Club holds its "Morning Meeting" every weekday at 10:20 a.m. ET.'),
    ("CNBC", "2026-11-17T15:00:01", "Homebuilder sentiment plunges to 14-year low, leading more builders to drop prices",
     "Homebuilder sentiment fell to a 14-year low amid high mortgage rates and higher prices for energy, "
     "labor and materials. That caused more builder price cuts."),
]


def _rank_real_titles(extra=()):
    candidates = [
        {"title": row[2], "source": row[0], "url": f"https://example.test/{i}",
         "published_at": row[1], "category": "markets", "why_it_matters": row[-1]}
        for i, row in enumerate(_REAL_2026_11_17)
    ]
    output = build_catalysts.build_market_catalysts(
        candidates=[*candidates, *extra],
        market_date="2026-11-17",
        generated_at=_GENERATED_2026_11_17,
        weekly_mode=False,
    )
    return output["ranked"]


def test_world_news_without_market_topics_ranks_below_market_news():
    ranked = _rank_real_titles()
    position = {c["title"].split()[0]: i for i, c in enumerate(ranked)}
    market = [position["Wall"], position["Jensen"], position["Homebuilder"]]
    for off_topic in ("Eisenkot-led", "Bahrain", "Trump", "Estonia's", "Angola"):
        assert position[off_topic] > max(market), off_topic
    # Nothing is dropped and scores stay non-negative.
    assert len(ranked) == len(_REAL_2026_11_17)
    assert all(c["relevance_score"] >= 0 for c in ranked)


def test_market_vocabulary_counts_as_topics():
    for title in ("Wall Street ends lower ahead of Nvidia results",
                  "Homebuilder sentiment plunges to 14-year low",
                  "Crypto firm files for IPO", "New tariff hits bank shares"):
        assert build_catalysts.compute_topic_bonus(
            {"title": title, "why_it_matters": ""}, topics=build_catalysts.BASELINE_TOPICS,
        ) > 0, title


def test_no_topic_penalty_applies_only_to_non_official_items():
    now = datetime(2026, 11, 18, 3, 45, tzinfo=timezone.utc)
    base = {"title": "Estonia border plan", "why_it_matters": "", "published_at": "2026-11-17T20:00:00Z"}
    standard = build_catalysts.compute_relevance_score(
        {**base, "source": "Reuters", "url": "https://example.test/a", "source_tier": "premium"}, now=now)
    official = build_catalysts.compute_relevance_score(
        {**base, "source": "BEA", "url": "https://www.bea.gov/x", "source_tier": "official"}, now=now)
    recency = 30.0 - (7.75 * 30.0 / 48.0)
    assert standard == pytest.approx(30.0 + recency - build_catalysts.NO_MARKET_TOPIC_PENALTY, abs=0.01)
    assert official == pytest.approx(60.0 + recency, abs=0.01)


def test_archived_official_release_does_not_top_fresh_fomc_statement_or_market_news():
    old_bea = {"title": "Travel and Tourism Satellite Accounts, 3rd quarter 2017", "source": "BEA",
               "url": "https://www.bea.gov/news/2017/travel", "published_at": "2017-12-13T08:30:00-05:00",
               "category": "macro", "why_it_matters": ""}
    fomc = {"title": "Federal Reserve issues FOMC statement", "source": "Federal Reserve",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261117a.htm",
            "published_at": "2026-11-17T19:00:00Z", "category": "monetary_policy", "why_it_matters": ""}
    ranked = _rank_real_titles(extra=[old_bea, fomc])
    titles = [c["title"] for c in ranked]
    assert titles[0] == fomc["title"]
    assert titles.index(old_bea["title"]) > titles.index(
        "Wall Street ends lower ahead of Nvidia results, focus turns to Anthropic debut - Reuters")


def test_official_age_penalty_is_gradual_and_capped():
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    def score(published):
        return build_catalysts.compute_relevance_score(
            {"title": "Release", "why_it_matters": "", "source": "BEA",
             "url": "https://www.bea.gov/x", "published_at": published}, now=now)
    week_old = score("2026-11-11T00:00:00Z")
    month_old = score("2026-10-28T00:00:00Z")
    ancient = score("2017-12-13T00:00:00Z")
    assert week_old == pytest.approx(60.0)
    assert ancient < month_old < week_old
    assert ancient == pytest.approx(60.0 - build_catalysts.OFFICIAL_AGE_PENALTY_MAX)
