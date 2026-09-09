"""CI reuse must reduce downloads without carrying old prices into a new run."""

import json
from unittest.mock import Mock

import pandas as pd
import pytest

from shared.cache_manager import CachedDataFetcher
from shared.yf_retry import with_429_retry
import shared.yf_retry as retry_module


@pytest.fixture
def downloads(monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', '100')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    frame = pd.DataFrame(
        {('Close', 'AAA'): [10.0, 11.0]},
        index=pd.date_range('2026-09-08', periods=2),
    )
    download = Mock(return_value=frame)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', download)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', download)
    return download


def fetch(tmp_path, **kwargs):
    request = dict(tickers=['AAA'], period='2y', cache_name='breadth', reuse_within_run=True)
    request.update(kwargs)
    return CachedDataFetcher(tmp_path).fetch_prices(**request)


def test_five_consumers_download_once_in_same_attempt(tmp_path, downloads):
    for _ in range(5):
        pd.testing.assert_frame_equal(fetch(tmp_path), downloads.return_value, check_freq=False)
    assert downloads.call_count == 1


@pytest.mark.parametrize('change', ['run', 'attempt', 'tickers', 'period', 'force', 'local', 'disabled', 'corrupt'])
def test_changed_or_untrusted_requests_refresh(tmp_path, downloads, monkeypatch, change):
    fetch(tmp_path)
    kwargs = {}
    if change == 'run':
        monkeypatch.setenv('GITHUB_RUN_ID', '101')
    elif change == 'attempt':
        monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    elif change == 'tickers':
        kwargs['tickers'] = ['BBB']  # Same count is not the same universe.
    elif change == 'period':
        kwargs['period'] = '5y'
    elif change == 'force':
        kwargs['force_refresh'] = True
    elif change == 'local':
        monkeypatch.delenv('GITHUB_RUN_ID')
    elif change == 'disabled':
        kwargs['reuse_within_run'] = False
    else:
        (tmp_path / 'breadth.parquet').write_text('corrupt')
    fetch(tmp_path, **kwargs)
    assert downloads.call_count == 2


def test_failed_refresh_does_not_mark_stale_cache_reusable(tmp_path, downloads, monkeypatch):
    fetch(tmp_path)
    before = json.loads((tmp_path / 'breadth_metadata.json').read_text())
    monkeypatch.setenv('GITHUB_RUN_ID', '101')
    downloads.return_value = pd.DataFrame()
    fetch(tmp_path)
    fetch(tmp_path)
    assert downloads.call_count == 3
    assert json.loads((tmp_path / 'breadth_metadata.json').read_text()) == before


@pytest.mark.parametrize('empty', [None, pd.DataFrame(), pd.DataFrame({'Close': [float('nan')]})])
def test_swallowed_yahoo_errors_retry_then_recover(empty, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(retry_module.time, 'sleep', sleep)
    valid = pd.DataFrame({'Close': [100.0]})
    download = Mock(side_effect=[empty, valid])
    assert with_429_retry(download, retry_empty=True) is valid
    assert download.call_count == 2
    sleep.assert_called_once_with(30.0)


def test_empty_retry_exhaustion_returns_empty_for_publication_guard(monkeypatch):
    monkeypatch.setattr(retry_module.time, 'sleep', Mock())
    empty = pd.DataFrame()
    download = Mock(return_value=empty)
    assert with_429_retry(download, retry_empty=True) is empty
    assert download.call_count == 2


def test_valid_and_partial_responses_are_not_retried(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(retry_module.time, 'sleep', sleep)
    frame = pd.DataFrame({'AAA': [100.0], 'BBB': [float('nan')]})
    download = Mock(return_value=frame)
    assert with_429_retry(download, retry_empty=True) is frame
    download.assert_called_once_with()
    sleep.assert_not_called()
