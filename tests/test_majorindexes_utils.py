import importlib.util
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "majorindexes_utils", Path(__file__).resolve().parent.parent / "majorindexes" / "utils.py")
utils = importlib.util.module_from_spec(_spec)  # unique name: impliedvol also has utils.py
_spec.loader.exec_module(utils)


def test_return_and_52_week_metrics_ignore_non_finite_closes():
    prices = pd.Series(
        [100.0] * 127 + [np.nan],
        index=pd.date_range("2025-01-01", periods=128),
    )

    returns = utils.calculate_returns(prices)
    week_52_metrics = utils.calculate_52_week_metrics(prices)

    assert returns["1_month_percent"] == 0.0
    assert returns["3_month_percent"] == 0.0
    assert returns["6_month_percent"] == 0.0
    assert week_52_metrics["distance_from_52w_high_percent"] == 0.0


def test_statistics_ignore_non_finite_closes():
    prices = pd.Series(
        [100.0, 101.0, np.nan],
        index=pd.date_range("2025-01-01", periods=3),
    )

    statistics = utils.calculate_statistics(prices)

    assert statistics["period_return_percent"] == 1.0
    assert all(
        value is None or not isinstance(value, float) or np.isfinite(value)
        for value in statistics.values()
    )


def test_save_json_rejects_non_finite_values(tmp_path):
    output = tmp_path / "snapshot.json"

    with pytest.raises(ValueError):
        utils.save_json({"percent": float("nan")}, str(output))


def test_save_json_emits_browser_parseable_json(tmp_path):
    output = tmp_path / "snapshot.json"

    utils.save_json({"percent": None, "value": np.float64(1.25)}, str(output))

    assert json.loads(output.read_text()) == {"percent": None, "value": 1.25}


@pytest.mark.parametrize('closes', [[100, np.nan], [np.nan, 101], [100, np.inf], [0, 101]])
def test_current_snapshot_rejects_unusable_closes(closes):
    frame = pd.DataFrame({'Close': closes})
    with pytest.raises(ValueError, match='closing prices must be finite and positive'):
        utils.get_current_snapshot(frame)


def test_current_snapshot_accepts_unchanged_prices():
    frame = pd.DataFrame({
        'Close': [100, 100], 'Open': [99, 100], 'High': [101, 101],
        'Low': [98, 99], 'Volume': [1000, 1200],
    })
    snapshot = utils.get_current_snapshot(frame)
    assert snapshot['current_price'] == 100
    assert snapshot['daily_change_percent'] == 0


@pytest.mark.parametrize('utc_instant,expected', [
    # 13:45 UTC is 08:45 EST the Friday before DST starts (2026-03-08)...
    ('2026-03-06T13:45:00+00:00', 'pre'),
    # ...and 09:45 EDT the Monday after, once New York is UTC-4.
    ('2026-03-09T13:45:00+00:00', 'during'),
    # 20:30 UTC is 16:30 EDT before DST ends (2026-11-01) and 15:30 EST after.
    ('2026-10-30T20:30:00+00:00', 'post'),
    ('2026-11-02T20:30:00+00:00', 'during'),
])
def test_market_hours_status_follows_new_york_dst(monkeypatch, utc_instant, expected):
    instant = datetime.fromisoformat(utc_instant)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(utils, 'datetime', FrozenDatetime)
    assert utils.get_market_hours_status() == expected
