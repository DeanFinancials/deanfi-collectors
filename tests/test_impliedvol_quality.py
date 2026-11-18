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
