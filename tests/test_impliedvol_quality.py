"""Implied-volatility quality guard: Yahoo placeholder IVs must not be published."""

import sys
from pathlib import Path

import pandas as pd

IMPLIEDVOL_DIR = Path(__file__).resolve().parent.parent / "impliedvol"
sys.path.insert(0, str(IMPLIEDVOL_DIR))

import utils as iv_utils  # noqa: E402

sys.path.remove(str(IMPLIEDVOL_DIR))
sys.modules.pop("utils", None)


def _leg(strike, iv, bid, ask):
    return pd.Series({"strike": strike, "impliedVolatility": iv, "bid": bid, "ask": ask})


def test_unquoted_placeholder_iv_is_not_usable():
    # Observed for DIA pre-market on 2026-11-18: bid/ask 0, IV 0.000987 and 1e-05.
    assert not iv_utils.is_usable_iv(_leg(507.5, 0.000987, 0.0, 0.0))
    assert not iv_utils.is_usable_iv(_leg(507.5, 1e-05, 0.0, 0.0))
    assert not iv_utils.is_usable_iv(_leg(507.5, 0.0005, 6.1, 6.5))
    assert not iv_utils.is_usable_iv(_leg(507.5, float("nan"), 6.1, 6.5))
    assert iv_utils.is_usable_iv(_leg(732.0, 0.245308, 10.51, 10.83))


def test_average_usable_iv_marks_missing_instead_of_publishing_placeholders():
    average, basis = iv_utils.average_usable_iv(
        _leg(507.5, 0.000987, 0.0, 0.0), _leg(507.5, 1e-05, 0.0, 0.0)
    )
    assert average is None
    assert basis == "unavailable"


def test_average_usable_iv_uses_only_quoted_legs():
    average, basis = iv_utils.average_usable_iv(
        _leg(732.0, 0.24, 10.5, 10.8), _leg(732.0, 1e-05, 0.0, 0.0)
    )
    assert average == 0.24
    assert basis == "call_only"

    average, basis = iv_utils.average_usable_iv(
        _leg(732.0, 0.24, 10.5, 10.8), _leg(732.0, 0.20, 8.3, 8.8)
    )
    assert average == 0.22
    assert basis == "call_put_average"


def test_find_atm_option_prefers_nearest_quoted_strike():
    chain = pd.DataFrame(
        [
            {"strike": 507.0, "impliedVolatility": 0.000987, "bid": 0.0, "ask": 0.0},
            {"strike": 508.0, "impliedVolatility": 0.18, "bid": 6.0, "ask": 6.4},
        ]
    )
    picked = iv_utils.find_atm_option(chain, 507.1, tolerance=0.02)
    assert picked["strike"] == 508.0


def test_find_atm_option_falls_back_to_nearest_strike_when_nothing_is_quoted():
    chain = pd.DataFrame(
        [
            {"strike": 507.0, "impliedVolatility": 0.000987, "bid": 0.0, "ask": 0.0},
            {"strike": 508.0, "impliedVolatility": 1e-05, "bid": 0.0, "ask": 0.0},
        ]
    )
    picked = iv_utils.find_atm_option(chain, 507.1, tolerance=0.02)
    assert picked["strike"] == 507.0


def test_formatting_helpers_accept_missing_iv():
    assert iv_utils.format_iv_percentage(None) is None
    assert iv_utils.classify_iv_level(None) is None
    assert iv_utils.format_iv_percentage(0.226814) == "22.68%"


# --- carry-forward of the last good IV -------------------------------------
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import yaml  # noqa: E402

NOW = datetime.fromisoformat("2026-11-18T08:14:00-05:00")
FRESH_PRIOR = {"symbol": "DIA", "average_iv": 0.152, "iv_basis": "call_put_average",
               "timestamp": "2026-11-17T15:55:00-05:00"}


def test_fresh_iv_is_marked_not_stale():
    snap = {"symbol": "SPY", "average_iv": 0.18, "iv_basis": "call_put_average",
            "timestamp": "2026-11-18T10:00:00-05:00"}
    iv_utils.apply_iv_carry_forward(snap, FRESH_PRIOR, now=NOW)
    assert snap["average_iv"] == 0.18
    assert snap["iv_stale"] is False
    assert snap["iv_as_of"] == "2026-11-18T10:00:00-05:00"


def test_missing_iv_carries_forward_last_good_value():
    snap = {"symbol": "DIA", "average_iv": None, "iv_basis": "unavailable",
            "timestamp": "2026-11-18T08:14:00-05:00"}
    iv_utils.apply_iv_carry_forward(snap, FRESH_PRIOR, now=NOW)
    assert snap["average_iv"] == 0.152
    assert snap["iv_stale"] is True
    assert snap["iv_as_of"] == FRESH_PRIOR["timestamp"]
    assert snap["iv_basis"] == "carried_forward"
    assert snap["iv_carried_basis"] == "call_put_average"
    # Formatting stays usable for the carried value.
    assert iv_utils.format_iv_percentage(snap["average_iv"]) == "15.20%"


def test_repeated_carry_forward_keeps_original_as_of_and_expires():
    first = {"symbol": "DIA", "average_iv": None, "timestamp": "2026-11-18T08:14:00-05:00"}
    iv_utils.apply_iv_carry_forward(first, FRESH_PRIOR, now=NOW)
    later = datetime.fromisoformat("2026-11-20T08:00:00-05:00")
    second = {"symbol": "DIA", "average_iv": None, "timestamp": later.isoformat()}
    iv_utils.apply_iv_carry_forward(second, first, now=later)
    assert second["iv_as_of"] == FRESH_PRIOR["timestamp"]
    assert second["iv_carried_basis"] == "call_put_average"
    expired_at = datetime.fromisoformat("2026-11-22T08:00:00-05:00")
    third = {"symbol": "DIA", "average_iv": None, "timestamp": expired_at.isoformat()}
    iv_utils.apply_iv_carry_forward(third, second, now=expired_at)
    assert third["average_iv"] is None
    assert third["iv_stale"] is False
    assert third["iv_as_of"] is None


def test_placeholder_or_missing_prior_is_not_carried_forward():
    # Pre-c016e36 snapshots published Yahoo placeholders such as 0.000498.
    for prior in ({**FRESH_PRIOR, "average_iv": 0.000498}, {**FRESH_PRIOR, "average_iv": None},
                  {**FRESH_PRIOR, "timestamp": "not a date"}, None, {}):
        snap = {"symbol": "XLP", "average_iv": None, "timestamp": NOW.isoformat()}
        iv_utils.apply_iv_carry_forward(snap, prior, now=NOW)
        assert snap["average_iv"] is None, prior
        assert snap["iv_stale"] is False


def test_load_prior_snapshot_reads_published_file(tmp_path, monkeypatch):
    (tmp_path / "major_indices_iv_snapshot.json").write_text(json.dumps({"data": {"DIA": FRESH_PRIOR}}))
    (tmp_path / "broken.json").write_text("{")
    monkeypatch.setenv(iv_utils.PRIOR_SNAPSHOT_DIR_ENV, str(tmp_path))
    assert iv_utils.load_prior_snapshot("major_indices_iv_snapshot.json")["DIA"]["average_iv"] == 0.152
    assert iv_utils.load_prior_snapshot("broken.json") == {}
    assert iv_utils.load_prior_snapshot("missing.json") == {}
    monkeypatch.delenv(iv_utils.PRIOR_SNAPSHOT_DIR_ENV)
    assert iv_utils.load_prior_snapshot("major_indices_iv_snapshot.json") == {}


def test_market_workflows_point_iv_fetchers_at_published_snapshots():
    workflows = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    for name in ("market-data-intraday.yml", "market-data-close.yml"):
        steps = yaml.safe_load((workflows / name).read_text())["jobs"]["fetch-and-publish"]["steps"]
        names = [step.get("name") for step in steps]
        iv_step = steps[names.index("Fetch implied volatility")]
        assert iv_step["env"]["IV_PRIOR_SNAPSHOT_DIR"].endswith("data-cache/implied-volatility"), name
        assert names.index("Checkout data repo") < names.index("Fetch implied volatility"), name
