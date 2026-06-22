from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_options_whales_cli_accepts_lookback_override():
    source = (REPO_ROOT / "optionswhales/fetch_options_whales.py").read_text(encoding="utf-8")

    assert "parser.add_argument('--lookback'" in source
    assert "config['collection']['lookback_trading_days'] = args.lookback" in source
