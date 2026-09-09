"""Avoid duplicate publications when independent and backup triggers overlap."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SECTIONS = ('advance-decline', 'major-indexes', 'meanreversion', 'implied-volatility')


def collection_due(now, freshness):
    et = now.astimezone(ZoneInfo('America/New_York'))
    if et.weekday() >= 5 or not 8 <= et.hour < 17:
        return False, 'outside collection hours'
    try:
        ages = [(now - datetime.fromisoformat(
            freshness['sections'][section]['last_updated'].replace('Z', '+00:00')
        )).total_seconds() for section in SECTIONS]
        if all(0 <= age < 10 * 60 for age in ages):
            return False, 'all intraday sections were published within 10 minutes'
    except (KeyError, TypeError, ValueError):
        pass
    return True, 'collection is due'


if __name__ == '__main__':
    try:
        freshness = json.loads(Path('data-cache/data_freshness.json').read_text())
    except (OSError, ValueError):
        freshness = {}
    due, reason = collection_due(datetime.now(timezone.utc), freshness)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'in_market_hours={str(due).lower()}\n')
    print(f'Collector active={due}: {reason}')
