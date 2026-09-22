import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

MAJORINDEXES_DIR = Path(__file__).resolve().parent.parent / "majorindexes"
sys.path.insert(0, str(MAJORINDEXES_DIR))

import utils  # noqa: E402


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

    with pytest.raises(ValueError, match="Out of range float values"):
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
