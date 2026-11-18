"""The workflow's manual lookback_days input reaches the collector as --lookback."""

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_collector():
    # The collector does `from utils import ...`, a name several collector
    # directories share, so import it against its own utils and then restore.
    saved_utils = sys.modules.pop("utils", None)
    sys.path.insert(0, str(REPO_ROOT / "optionswhales"))
    try:
        return importlib.import_module("optionswhales.fetch_options_whales")
    finally:
        sys.path.remove(str(REPO_ROOT / "optionswhales"))
        sys.modules.pop("utils", None)
        if saved_utils is not None:
            sys.modules["utils"] = saved_utils


whales = _import_collector()


def _run_main(monkeypatch, *argv):
    config = {
        "collection": {"lookback_trading_days": 5},
        "api_keys": {"api_key_env": "TEST_WHALES_KEY", "api_secret_env": "TEST_WHALES_SECRET"},
    }
    monkeypatch.setattr(whales, "load_config", lambda: config)
    monkeypatch.delenv("TEST_WHALES_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["fetch_options_whales.py", *argv])
    # Missing API keys stop main() right after argument handling, before any network call.
    with pytest.raises(SystemExit) as exc:
        whales.main()
    return config, exc.value.code


def test_lookback_override_is_applied(monkeypatch):
    config, _ = _run_main(monkeypatch, "--lookback", "3")
    assert config["collection"]["lookback_trading_days"] == 3


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_invalid_lookback_is_rejected(monkeypatch, value):
    config, code = _run_main(monkeypatch, "--lookback", value)
    assert code == 2
    assert config["collection"]["lookback_trading_days"] == 5
