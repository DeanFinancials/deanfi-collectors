"""ETF fund flows must not write an all-null session over the last good month files.

The workflow seeds etffundflows/output/ from deanfi-data, the script upserts
into those files in place, and the workflow publishes them. If every ticker
fails, the script must exit non-zero before writing anything. A first run
(nothing seeded, every ticker ``missing_prior_day``) is not a failure.

All provider calls are mocked; no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "etffundflows"))

import fetch_etf_fund_flows as fff  # noqa: E402

SESSION = "2026-11-18"
PRIOR = "2026-11-17"
TICKERS = ["SPY", "TLT", "XLE"]
PREFIXES = [
    "etf_fund_flows",
    "etf_fund_flows_agg_asset_class",
    "etf_fund_flows_agg_category",
    "etf_fund_flows_agg_subcategory",
]

POINT_KEYS = {
    "date", "aum", "nav", "close", "aum_nav_updated_at", "aum_nav_source",
    "return_factor_nav", "return_factor_close", "flow_nav", "flow_close",
    "flow_nav_pct_aum", "flow_close_pct_aum", "implied_shares",
    "asset_class", "category", "subcategory", "notes", "warnings",
}
TICKER_NODE_KEYS = {"ticker", "asset_class", "category", "subcategory", "notes", "daily"}
METADATA_KEYS = {
    "month", "generated_at", "data_source", "calculation", "tickers_total",
    "aum_nav_calls", "aum_nav_call_caps", "aum_nav_call_caps_applied",
}
AGG_GROUP_KEYS = {
    "aum", "flow_nav", "flow_close", "tickers",
    "tickers_with_aum", "tickers_with_flow_nav", "tickers_with_flow_close",
}


def _write_config(tmp_path: Path) -> Path:
    cfg = yaml.safe_load((REPO_ROOT / "etffundflows" / "config.yml").read_text())
    cfg["aum_nav"]["source_order"] = ["yfinance"]  # no Alpha Vantage sleeps
    cfg["output"]["directory"] = str(tmp_path / "output")
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _seed_prior_day(out: Path) -> None:
    """A published month file holding PRIOR for every ticker (what the workflow seeds)."""
    out.mkdir(parents=True, exist_ok=True)
    data = {
        t: {"ticker": t, "asset_class": "", "category": "", "subcategory": "", "notes": "",
            "daily": [{"date": PRIOR, "aum": 100.0, "nav": 10.0, "close": 10.0}]}
        for t in TICKERS
    }
    (out / "etf_fund_flows_2026-11.json").write_text(json.dumps(
        {"_README": {}, "metadata": {"month": "2026-11"}, "data": data}, indent=2))
    for prefix in PREFIXES[1:]:
        (out / f"{prefix}_2026-11.json").write_text(json.dumps(
            {"_README": {}, "metadata": {}, "data": {"daily": [{"date": PRIOR, "groups": {"": {"aum": 300.0}}}]}}))


def _snapshot(out: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(out.glob("*.json"))} if out.exists() else {}


def _run(monkeypatch, tmp_path: Path, aum_nav: dict, closes: dict) -> int:
    """Run main() with mocked providers; return its exit code (SystemExit or return value)."""
    monkeypatch.setattr(fff, "yfinance_etf_aum_nav", lambda t: aum_nav.get(t, (None, None, None)))
    monkeypatch.setattr(fff, "yfinance_fetch_closes", lambda tickers, start, end: closes)

    def no_download(*a, **k):  # pragma: no cover - --session-date skips detection
        raise AssertionError("unexpected yf.download")

    monkeypatch.setattr(fff.yf, "download", no_download)
    monkeypatch.setattr(sys, "argv", [
        "fetch_etf_fund_flows.py", "--config", str(_write_config(tmp_path)),
        "--tickers", ",".join(TICKERS), "--session-date", SESSION,
    ])
    try:
        return fff.main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


GOOD = {t: (110.0, 10.5, "2026-11-18T21:00:00Z") for t in TICKERS}
GOOD_CLOSES = {t: {SESSION: 10.5} for t in TICKERS}


@pytest.mark.parametrize("aum_nav, closes", [
    ({}, {}),  # yfinance info and price download both failed
    ({}, GOOD_CLOSES),  # info blocked, closes fine: points carry no AUM
    ({t: (None, 10.5, None) for t in TICKERS}, GOOD_CLOSES),  # NAV but no AUM anywhere
    ({t: (float("nan"), None, None) for t in TICKERS}, {}),
], ids=["nothing", "close-only", "nav-only", "nan-aum"])
def test_all_tickers_fail_exits_nonzero_and_keeps_seeded_files(monkeypatch, tmp_path, capsys, aum_nav, closes):
    out = tmp_path / "output"
    _seed_prior_day(out)
    before = _snapshot(out)

    code = _run(monkeypatch, tmp_path, aum_nav, closes)

    assert code != 0
    assert _snapshot(out) == before, "seeded month files must be left byte-for-byte unchanged"
    assert "0/3 tickers succeeded" in capsys.readouterr().err


def test_all_tickers_fail_on_first_run_writes_nothing(monkeypatch, tmp_path):
    code = _run(monkeypatch, tmp_path, {}, {})

    assert code != 0
    assert _snapshot(tmp_path / "output") == {}


def _assert_output_contract(out: Path) -> dict:
    doc = json.loads((out / "etf_fund_flows_2026-11.json").read_text())
    assert set(doc) == {"_README", "data", "metadata"}
    assert METADATA_KEYS <= set(doc["metadata"])
    for t, node in doc["data"].items():
        assert set(node) == TICKER_NODE_KEYS, t
        for p in node["daily"]:
            if p["date"] == SESSION:
                assert set(p) == POINT_KEYS, t
    for prefix in PREFIXES[1:]:
        agg = json.loads((out / f"{prefix}_2026-11.json").read_text())
        assert set(agg) == {"_README", "metadata", "data"}
        day = [d for d in agg["data"]["daily"] if d["date"] == SESSION]
        assert len(day) == 1
        for group in day[0]["groups"].values():
            assert set(group) == AGG_GROUP_KEYS
    return doc


def test_normal_run_with_seeded_history_succeeds(monkeypatch, tmp_path):
    out = tmp_path / "output"
    _seed_prior_day(out)

    code = _run(monkeypatch, tmp_path, GOOD, GOOD_CLOSES)

    assert code == 0
    doc = _assert_output_contract(out)
    spy = doc["data"]["SPY"]["daily"]
    assert [p["date"] for p in spy] == [PRIOR, SESSION]  # history kept, session appended
    assert spy[-1]["flow_nav"] == pytest.approx(110.0 - 100.0 * 1.05)
    assert "missing_prior_day" not in spy[-1]["warnings"]


def test_seeded_first_run_with_missing_prior_day_succeeds(monkeypatch, tmp_path):
    """Nothing to seed: every ticker is missing_prior_day and every flow is null, but AUM is there."""
    code = _run(monkeypatch, tmp_path, GOOD, GOOD_CLOSES)

    assert code == 0
    doc = _assert_output_contract(tmp_path / "output")
    for node in doc["data"].values():
        point = node["daily"][-1]
        assert "missing_prior_day" in point["warnings"]
        assert point["flow_nav"] is None and point["aum"] == 110.0


def test_partial_failure_and_some_missing_prior_day_succeeds(monkeypatch, tmp_path):
    out = tmp_path / "output"
    _seed_prior_day(out)
    doc = json.loads((out / "etf_fund_flows_2026-11.json").read_text())
    del doc["data"]["TLT"]  # TLT newly added to the universe: no prior point
    (out / "etf_fund_flows_2026-11.json").write_text(json.dumps(doc))

    aum_nav = {"SPY": GOOD["SPY"], "TLT": GOOD["TLT"]}  # XLE fails outright
    code = _run(monkeypatch, tmp_path, aum_nav, GOOD_CLOSES)

    assert code == 0
    doc = _assert_output_contract(out)
    assert "missing_prior_day" in doc["data"]["TLT"]["daily"][-1]["warnings"]
    assert doc["data"]["XLE"]["daily"][-1]["aum"] is None


def test_is_usable_point():
    assert fff.is_usable_point({"aum": 1.0, "flow_nav": None, "warnings": ["missing_prior_day"]})
    assert not fff.is_usable_point({"aum": None, "nav": 10.0, "close": 10.0})
    assert not fff.is_usable_point({"aum": float("nan")})
