"""CI reuse must reduce downloads without carrying old prices into a new run."""

import json
from unittest.mock import Mock

import pandas as pd
import pytest

from shared.cache_manager import CachedDataFetcher

try:
    import pyarrow  # noqa: F401
except ImportError:  # pragma: no cover - environment-dependent
    pyarrow = None

# Without a parquet engine every save fails, so reuse never happens and the
# "refresh" assertions would pass vacuously. CI installs requirements.txt.
pytestmark = pytest.mark.skipif(
    pyarrow is None, reason="pyarrow (requirements.txt) is needed for the parquet cache"
)


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



def _fail_parquet_writes(monkeypatch):
    def boom(self, *args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(pd.DataFrame, 'to_parquet', boom)


@pytest.mark.parametrize('request_kwargs', [{}, {'period': None, 'start_date': '2026-09-01'}],
                         ids=['period', 'dates'])
def test_failed_parquet_save_writes_no_metadata(tmp_path, downloads, monkeypatch, request_kwargs):
    _fail_parquet_writes(monkeypatch)
    fetch(tmp_path, **request_kwargs)
    assert not (tmp_path / 'breadth_metadata.json').exists()


def test_failed_parquet_save_keeps_previous_metadata(tmp_path, downloads, monkeypatch):
    fetch(tmp_path)
    before = (tmp_path / 'breadth_metadata.json').read_text()
    monkeypatch.setenv('GITHUB_RUN_ID', '101')  # new run: refresh, then the save fails
    _fail_parquet_writes(monkeypatch)
    fetch(tmp_path)
    assert (tmp_path / 'breadth_metadata.json').read_text() == before
