from datetime import datetime, timedelta, timezone

import pytest

from scripts.check_market_collection import SECTIONS, collection_due

NOW = datetime(2026, 9, 9, 18, 52, tzinfo=timezone.utc)


def freshness(minutes):
    return {'sections': {section: {'last_updated': (NOW - timedelta(minutes=minutes)).isoformat()}
                         for section in SECTIONS}}


def test_recent_complete_publication_skips_duplicate():
    assert collection_due(NOW, freshness(5))[0] is False


@pytest.mark.parametrize('minutes', [10, 15, 1000, -5])
def test_due_or_future_timestamps_do_not_suppress_collection(minutes):
    assert collection_due(NOW, freshness(minutes))[0] is True


def test_one_stale_or_missing_section_still_collects():
    data = freshness(5)
    data['sections']['major-indexes'] = freshness(20)['sections']['major-indexes']
    assert collection_due(NOW, data)[0] is True
    del data['sections']['major-indexes']
    assert collection_due(NOW, data)[0] is True
    assert collection_due(NOW, {})[0] is True


@pytest.mark.parametrize('date', ['2026-09-12T18:00:00+00:00', '2026-09-09T21:00:00+00:00',
                                 '2026-12-09T12:59:00+00:00'])
def test_weekends_and_closed_hours_do_not_collect(date):
    assert collection_due(datetime.fromisoformat(date), {})[0] is False
