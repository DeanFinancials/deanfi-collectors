"""Contract for the major-indexes files the website reads from R2.

Runs the real fetch_us_major / fetch_sectors builders with only Yahoo faked
(one trailing placeholder row with no Close, as Yahoo returns intraday) and
asserts the fields deanfi-website reads:

- us_major_indices.json: MarketTicker.astro, HomeMarketTerminal.tsx,
  MajorIndexesSnapshot.tsx, MajorIndexesDashboard.tsx (metadata + indices[sym]).
- us_major_indices_historical.json: VIXHistoricalChart.tsx,
  utils/home-market-data.ts (indices[sym].data[].date/close).
- us_sector_indices.json: SectorDashboard.tsx, SnapshotSummary.tsx,
  MajorIndexesSnapshot.tsx, HomeMarketTerminal.tsx (metadata + sectors[sym]).
- us_sector_indices_historical.json: utils/sectors-data.ts,
  SectorPerformanceLineChart.tsx (sectors[sym].data[].date/close).
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest

from tests.test_batch_fetch import batch, load, ohlcv  # noqa: F401  (load is a fixture)

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MARKET_STATUS = {"pre", "during", "post", "closed"}
WEBSITE_MAJOR_SYMBOLS = {"^GSPC", "^DJI", "^IXIC", "^NDX", "^RUT", "^VIX"}  # MarketTicker.astro


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@pytest.fixture
def outputs(load, tmp_path):
    produced = {}
    for module_name in ("fetch_us_major", "fetch_sectors"):
        module, download, symbols = load(module_name)
        closes = list(np.linspace(100, 130, 59)) + [np.nan]
        download.return_value = batch({s: ohlcv(closes) for s in symbols})
        module.create_snapshot_json()
        module.create_historical_json()
        produced[module_name] = symbols
    files = {p.name: json.loads(p.read_text()) for p in tmp_path.glob("*.json")}
    return files, produced


def assert_snapshot_metadata(metadata, count):
    assert TIMESTAMP.match(metadata["generated_at"])
    assert DATE.match(metadata["market_date"])
    assert metadata["market_status"] in MARKET_STATUS
    assert metadata["indices_count"] == count


def assert_history(rows):
    assert len(rows) > 1
    for row in rows:
        assert DATE.match(row["date"])
        assert finite(row["close"])  # home-market-data drops non-numbers; sectors-data divides by it


def test_us_major_snapshot_contract(outputs):
    files, symbols = outputs
    body = files["us_major_indices.json"]
    assert set(body["indices"]) == set(symbols["fetch_us_major"]) >= WEBSITE_MAJOR_SYMBOLS
    assert_snapshot_metadata(body["metadata"], len(symbols["fetch_us_major"]))
    for row in body["indices"].values():
        assert finite(row["current_price"]) and row["current_price"] > 0
        assert finite(row["daily_change"])
        assert finite(row["daily_change_percent"])


def test_us_major_historical_contract(outputs):
    files, symbols = outputs
    indices = files["us_major_indices_historical.json"]["indices"]
    assert set(indices) == set(symbols["fetch_us_major"])
    for row in indices.values():
        assert_history(row["data"])


def test_us_sector_snapshot_contract(outputs):
    files, symbols = outputs
    body = files["us_sector_indices.json"]
    assert set(body["sectors"]) == set(symbols["fetch_sectors"])
    assert_snapshot_metadata(body["metadata"], len(symbols["fetch_sectors"]))
    for row in body["sectors"].values():
        assert finite(row["current_price"]) and row["current_price"] > 0
        assert finite(row["daily_change_percent"])


def test_us_sector_historical_contract(outputs):
    files, symbols = outputs
    body = files["us_sector_indices_historical.json"]
    assert TIMESTAMP.match(body["metadata"]["generated_at"])
    assert set(body["sectors"]) == set(symbols["fetch_sectors"])
    for row in body["sectors"].values():
        assert isinstance(row["name"], str) and isinstance(row["sector_name"], str)
        assert_history(row["data"])
