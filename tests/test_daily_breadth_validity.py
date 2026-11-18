import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def breadth_module(monkeypatch):
    # Network access is irrelevant to these calculation-only regression tests.
    monkeypatch.setitem(sys.modules, 'yfinance', types.ModuleType('yfinance'))
    universe = types.ModuleType('shared.spx_universe')
    universe.fetch_spx_tickers = lambda: []
    cache = types.ModuleType('shared.cache_manager')
    cache.CachedDataFetcher = object
    monkeypatch.setitem(sys.modules, 'shared.spx_universe', universe)
    monkeypatch.setitem(sys.modules, 'shared.cache_manager', cache)
    path = Path(__file__).resolve().parents[1] / 'advancedecline/fetch_daily_breadth.py'
    spec = importlib.util.spec_from_file_location('daily_breadth_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'load_latest_ad_line', lambda: (None, None, None))
    return module


@pytest.mark.parametrize('closes', [[[100, 101], [np.nan, np.nan]], [[np.nan, np.nan], [100, 101]]])
def test_breadth_rejects_no_comparable_closes(breadth_module, closes):
    data = {'Close': pd.DataFrame(closes)}
    with pytest.raises(ValueError, match='No usable current/prior close pairs'):
        breadth_module.calculate_daily_breadth(data, {})


def test_flat_trading_session_is_not_missing_data(breadth_module):
    prices = pd.DataFrame({'A': [100.0] * 252, 'B': [110.0] * 252},
                          index=pd.date_range('2025-01-01', periods=252))
    data = {'Close': prices, 'High': prices, 'Low': prices, 'Volume': prices * 10}
    result = breadth_module.calculate_daily_breadth(
        data, {'new_high_threshold': 0.99, 'new_low_threshold': 1.01})
    assert result['advances_declines']['unchanged'] == 2
    assert result['advances_declines']['total_stocks'] == 2


@pytest.mark.parametrize('cached', [False, True])
def test_download_retries_nonempty_unusable_latest_closes(breadth_module, monkeypatch, cached):
    from unittest.mock import Mock

    invalid = {'Close': pd.DataFrame({'A': [100.0, 101.0, np.nan]})}
    valid = {'Close': pd.DataFrame({'A': [100.0, 101.0, 102.0]})}
    download = Mock(side_effect=[invalid, valid])
    sleep = Mock()
    monkeypatch.setattr(breadth_module.time, 'sleep', sleep)
    if cached:
        fetcher = Mock(fetch_prices=download)
        monkeypatch.setattr(breadth_module, 'CachedDataFetcher', Mock(return_value=fetcher))
    else:
        monkeypatch.setattr(breadth_module.yf, 'download', download, raising=False)
    result = breadth_module.download_market_data(['A'], cache_dir='cache' if cached else None)
    assert result is valid
    assert download.call_count == 2
    sleep.assert_called_once()
    if cached:
        assert download.call_args_list[0].kwargs['force_refresh'] is False
        assert download.call_args_list[1].kwargs['force_refresh'] is True


def test_download_exhaustion_still_rejects_bad_snapshot(breadth_module, monkeypatch):
    from unittest.mock import Mock

    invalid = {'Close': pd.DataFrame({'A': [100.0, 101.0, np.nan]})}
    download = Mock(return_value=invalid)
    monkeypatch.setattr(breadth_module.yf, 'download', download, raising=False)
    monkeypatch.setattr(breadth_module.time, 'sleep', Mock())
    with pytest.raises(ValueError, match='No usable current/prior close pairs'):
        breadth_module.download_market_data(['A'])
    assert download.call_count == 2


def test_valid_partial_response_does_not_retry(breadth_module, monkeypatch):
    from unittest.mock import Mock

    data = {'Close': pd.DataFrame({'A': [100.0, 101.0], 'B': [np.nan, np.nan]})}
    download = Mock(return_value=data)
    monkeypatch.setattr(breadth_module.yf, 'download', download, raising=False)
    sleep = Mock()
    monkeypatch.setattr(breadth_module.time, 'sleep', sleep)
    assert breadth_module.download_market_data(['A', 'B']) is data
    assert download.call_count == 1
    sleep.assert_not_called()
