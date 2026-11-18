"""CI reuse must reduce downloads without carrying old prices into a new run."""

import json
from datetime import datetime, timedelta
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
    # An unreadable cache also turns the incremental refresh into a full one.
    assert downloads.call_count == (3 if change == 'corrupt' else 2)


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


def _prices(dates, value):
    return pd.DataFrame({('Close', 'AAA'): value, ('Close', 'BBB'): value},
                        index=pd.DatetimeIndex(dates))


def _final_bar(dates, cached_value, final_value):
    """An incremental download matching the cache except its newest (final) bar."""
    frame = _prices(dates, cached_value)
    frame.iloc[-1] = final_value
    return frame


def _warm_cache(tmp_path, monkeypatch, frame):
    """Save `frame` as a fresh (< 24h) cache, so the next fetch is incremental."""
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', Mock(return_value=frame))
    CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')


@pytest.mark.parametrize('env', [None, 'true'], ids=['unset', 'true'])
def test_intraday_default_falls_back_to_stale_cache(tmp_path, monkeypatch, env):
    cached = _prices(pd.bdate_range('2026-01-01', periods=30), 1.0)
    _warm_cache(tmp_path, monkeypatch, cached)
    if env is None:
        monkeypatch.delenv('PRICE_CACHE_ALLOW_STALE', raising=False)
    else:
        monkeypatch.setenv('PRICE_CACHE_ALLOW_STALE', env)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', Mock(return_value=pd.DataFrame()))
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')
    pd.testing.assert_frame_equal(result, cached, check_freq=False)


@pytest.mark.parametrize('failure', [None, pd.DataFrame()], ids=['exception', 'empty'])
@pytest.mark.parametrize('how', ['env', 'arg'])
def test_stale_fallback_disabled_returns_empty(tmp_path, monkeypatch, failure, how):
    _warm_cache(tmp_path, monkeypatch, _prices(pd.bdate_range('2026-01-01', periods=30), 1.0))
    download = Mock(return_value=failure)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', download)
    full = Mock(return_value=None)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', full)
    kwargs = {}
    if how == 'env':
        monkeypatch.setenv('PRICE_CACHE_ALLOW_STALE', 'false')
    else:
        kwargs['allow_stale'] = False
    fetcher = CachedDataFetcher(tmp_path, **kwargs)
    period_result = fetcher.fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')
    dates_result = fetcher.fetch_prices(['AAA', 'BBB'], start_date='2025-01-01', cache_name='close')
    assert download.call_count == 2 and full.call_count == 0
    assert isinstance(period_result, pd.DataFrame) and period_result.empty
    assert isinstance(dates_result, pd.DataFrame) and dates_result.empty


@pytest.mark.parametrize('rows', [30, 300, 5000])
@pytest.mark.parametrize('request_kwargs', [{'period': '2y'}, {'start_date': '2020-01-01'}],
                         ids=['period', 'dates'])
def test_downloaded_final_bar_replaces_cached_partial_bar(tmp_path, monkeypatch, rows, request_kwargs):
    # The cache's last row is today's partial intraday bar (1.0); the close
    # download returns the same earlier sessions and today's final bar (2.0).
    dates = pd.bdate_range(end='2026-11-18', periods=rows)
    _warm_cache(tmp_path, monkeypatch, _prices(dates, 1.0))
    final = _final_bar(dates[-5:], 1.0, 2.0)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', Mock(return_value=final))
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert len(result) == rows and result.index.is_monotonic_increasing
    assert (result.loc[dates[-1]] == 2.0).all()
    assert (result.loc[dates[:-1]] == 1.0).all().all()
    reloaded = pd.read_parquet(tmp_path / 'close.parquet')
    assert (reloaded.loc[dates[-1]] == 2.0).all()


def test_download_without_todays_bar_drops_cached_partial_bar(tmp_path, monkeypatch):
    dates = pd.bdate_range(end='2026-11-18', periods=30)
    _warm_cache(tmp_path, monkeypatch, _prices(dates, 1.0))
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates',
                        Mock(return_value=_final_bar(dates[-5:-1], 1.0, 2.0)))
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')
    assert result.index[-1] == dates[-2]
    assert (result.loc[dates[-2]] == 2.0).all()


ROWS = 300
DATES = pd.bdate_range(end='2026-11-18', periods=ROWS)
START = str(DATES[0].date())


def _break_cache(tmp_path, monkeypatch, how):
    cache_file = tmp_path / 'close.parquet'
    if how == 'corrupt':
        cache_file.write_bytes(b'not parquet')
    elif how == 'missing':
        cache_file.unlink()  # metadata still claims a cache
    else:  # pyarrow read error on an existing file
        def boom(*args, **kwargs):
            raise OSError('pyarrow read error')
        monkeypatch.setattr(pd, 'read_parquet', boom)


def _unreadable_cache_downloads(tmp_path, monkeypatch, how, full_result):
    """Warm a full cache, break it, and stub the incremental and full downloads."""
    _warm_cache(tmp_path, monkeypatch, _prices(DATES, 1.0))
    _break_cache(tmp_path, monkeypatch, how)
    incremental = _prices(DATES[-5:], 2.0)

    def by_dates(tickers, start, end=None):
        return full_result if start == START else incremental
    dates_download = Mock(side_effect=by_dates)
    period_download = Mock(return_value=full_result)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', dates_download)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', period_download)
    return dates_download, period_download


UNREADABLE = pytest.mark.parametrize('how', ['corrupt', 'missing', 'read_error'])
REQUESTS = pytest.mark.parametrize('request_kwargs', [{'period': '2y'}, {'start_date': START}],
                                   ids=['period', 'dates'])


@UNREADABLE
@REQUESTS
def test_unreadable_cache_rebuilds_full_history(tmp_path, monkeypatch, how, request_kwargs):
    full = _prices(DATES, 3.0)
    dates_download, period_download = _unreadable_cache_downloads(tmp_path, monkeypatch, how, full)
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    pd.testing.assert_frame_equal(result, full, check_freq=False)
    if 'period' in request_kwargs:
        assert period_download.call_count == 1
    else:
        assert any(c.args[1] == START for c in dates_download.call_args_list)
    monkeypatch.undo()  # restore pd.read_parquet before checking the saved cache
    saved = pd.read_parquet(tmp_path / 'close.parquet')
    assert len(saved) == ROWS
    metadata = json.loads((tmp_path / 'close_metadata.json').read_text())
    assert (metadata['data_start'], metadata['data_end']) == (START, '2026-11-18')


@pytest.mark.parametrize('allow_stale', [True, False], ids=['stale_allowed', 'stale_disallowed'])
@pytest.mark.parametrize('failure', [None, pd.DataFrame()], ids=['exception', 'empty'])
@UNREADABLE
@REQUESTS
def test_unreadable_cache_and_failed_full_download_returns_empty(
        tmp_path, monkeypatch, how, request_kwargs, failure, allow_stale):
    _unreadable_cache_downloads(tmp_path, monkeypatch, how, failure)
    cache_file = tmp_path / 'close.parquet'
    metadata_file = tmp_path / 'close_metadata.json'
    before = (cache_file.read_bytes() if cache_file.exists() else None, metadata_file.read_text())
    result = CachedDataFetcher(tmp_path, allow_stale=allow_stale).fetch_prices(
        ['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert isinstance(result, pd.DataFrame) and result.empty
    # Nothing truncated was saved: the cache files are exactly as before.
    after = (cache_file.read_bytes() if cache_file.exists() else None, metadata_file.read_text())
    assert after == before


@REQUESTS
def test_cold_start_downloads_full_range_once(tmp_path, monkeypatch, request_kwargs):
    full = _prices(DATES, 1.0)
    dates_download = Mock(return_value=full)
    period_download = Mock(return_value=full)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', dates_download)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', period_download)
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    pd.testing.assert_frame_equal(result, full, check_freq=False)
    assert dates_download.call_count + period_download.call_count == 1
    assert len(pd.read_parquet(tmp_path / 'close.parquet')) == ROWS


@REQUESTS
def test_readable_cache_merges_without_full_download(tmp_path, monkeypatch, request_kwargs):
    _warm_cache(tmp_path, monkeypatch, _prices(DATES, 1.0))
    dates_download = Mock(return_value=_final_bar(DATES[-5:], 1.0, 2.0))
    period_download = Mock()
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', dates_download)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', period_download)
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert len(result) == ROWS
    assert dates_download.call_count == 1 and period_download.call_count == 0
    assert dates_download.call_args.args[1] != START  # incremental window only


# --- dividend/split re-adjustment ----------------------------------------------
# yfinance downloads with auto_adjust=True, so cached prices carry the adjustment
# factor of the day they were downloaded. After an ex-dividend date or a split
# Yahoo rescales all earlier history; the cache must then match a fresh full
# download rather than keep old-factor rows under new ones.

FACTOR = 0.99  # a 1% ex-dividend re-adjustment of every earlier close


def _ohlc(dates, close):
    close = pd.Series(close, index=pd.DatetimeIndex(dates), dtype=float)
    columns = {}
    for ticker, scale in (('AAA', 1.0), ('BBB', 3.0)):
        for field, offset in (('Open', 0.0), ('High', 1.0), ('Low', -1.0), ('Close', 0.0)):
            columns[(field, ticker)] = (close + offset) * scale
        columns[('Volume', ticker)] = 1000.0
    return pd.DataFrame(columns)


def _adjusted(dates, factor=1.0):
    """Adjusted history as a fresh download returns it, prices scaled by `factor`."""
    frame = _ohlc(dates, [100.0 + i * 0.5 for i in range(len(dates))])
    prices = [c for c in frame.columns if c[0] != 'Volume']
    frame[prices] *= factor
    return frame


def _readjust_downloads(monkeypatch, full_frame, incremental_frame):
    dates_download = Mock(side_effect=lambda tickers, start, end=None:
                          full_frame if start == START else incremental_frame)
    period_download = Mock(return_value=full_frame)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_dates', dates_download)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', period_download)
    return dates_download, period_download


def _full_calls(dates_download, period_download):
    return period_download.call_count + sum(c.args[1] == START for c in dates_download.call_args_list)


def _ohlc_cache(tmp_path, monkeypatch, frame):
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    monkeypatch.setattr(CachedDataFetcher, '_download_with_period', Mock(return_value=frame))
    CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')


@REQUESTS
def test_readjusted_history_triggers_full_download(tmp_path, monkeypatch, request_kwargs):
    # Cached with the old factor; the fresh download rescales every earlier day
    # (only AAA went ex-dividend, so one ticker must be enough).
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(DATES))
    fresh = _adjusted(DATES)
    aaa = [c for c in fresh.columns if c[1] == 'AAA' and c[0] != 'Volume']
    fresh.loc[DATES[:-1], aaa] *= FACTOR
    dates_download, period_download = _readjust_downloads(monkeypatch, fresh, fresh.loc[DATES[-8:]])
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    pd.testing.assert_frame_equal(result, fresh, check_freq=False)
    assert _full_calls(dates_download, period_download) == 1
    saved = pd.read_parquet(tmp_path / 'close.parquet')
    pd.testing.assert_frame_equal(saved, fresh, check_freq=False)


@REQUESTS
def test_matching_overlap_except_partial_bar_merges(tmp_path, monkeypatch, request_kwargs):
    cached = _adjusted(DATES)
    cached.iloc[-1] = cached.iloc[-1] * 0.97  # today's partial intraday bar
    _ohlc_cache(tmp_path, monkeypatch, cached)
    fresh = _adjusted(DATES)
    # Float noise below the tolerance on overlapping full days is not an adjustment.
    fresh.loc[DATES[-8:-1], ('Close', 'BBB')] *= 1 + 1e-7
    dates_download, period_download = _readjust_downloads(monkeypatch, None, fresh.loc[DATES[-8:]])
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert _full_calls(dates_download, period_download) == 0
    pd.testing.assert_series_equal(result.loc[DATES[-1]], fresh.loc[DATES[-1]], check_names=False)
    pd.testing.assert_frame_equal(result.loc[DATES[:-8]], cached.loc[DATES[:-8]], check_freq=False)
    assert len(result) == ROWS


def test_incremental_window_overlaps_full_days_after_long_closure(tmp_path, monkeypatch):
    # The cache (refreshed under 24h ago) ends five days back, as after a long
    # holiday closure: the 5-day lookback alone would overlap only the cache's
    # last, possibly partial, bar, leaving nothing to compare.
    dates = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=5), periods=ROWS)
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(dates))
    dates_download, _ = _readjust_downloads(monkeypatch, None, _adjusted(dates).loc[dates[-3:]])
    CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], period='2y', cache_name='close')
    start = pd.Timestamp(dates_download.call_args.args[1])
    assert len(dates[(dates >= start) & (dates < dates[-1])]) >= 2


@pytest.mark.parametrize('allow_stale', [True, False], ids=['stale_allowed', 'stale_disallowed'])
@REQUESTS
def test_readjustment_full_download_failure(tmp_path, monkeypatch, request_kwargs, allow_stale):
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(DATES))
    fresh = _adjusted(DATES, FACTOR)
    _readjust_downloads(monkeypatch, None, fresh.loc[DATES[-8:]])
    result = CachedDataFetcher(tmp_path, allow_stale=allow_stale).fetch_prices(
        ['AAA', 'BBB'], cache_name='close', **request_kwargs)
    if allow_stale:  # previous behaviour: merge the incremental frame
        assert len(result) == ROWS
        pd.testing.assert_frame_equal(result.loc[DATES[-8:]], fresh.loc[DATES[-8:]], check_freq=False)
    else:
        assert isinstance(result, pd.DataFrame) and result.empty


def _set_metadata(tmp_path, **fields):
    path = tmp_path / 'close_metadata.json'
    metadata = json.loads(path.read_text())
    for key, value in fields.items():
        if value is None:
            metadata.pop(key, None)
        else:
            metadata[key] = value
    path.write_text(json.dumps(metadata))


def _hours_ago(hours):
    return (datetime.now() - timedelta(hours=hours)).isoformat()


@REQUESTS
def test_old_full_download_forces_rebuild_despite_fresh_update(tmp_path, monkeypatch, request_kwargs):
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(DATES))
    _set_metadata(tmp_path, last_update=_hours_ago(1), full_download_at=_hours_ago(169))
    fresh = _adjusted(DATES, FACTOR)
    # The incremental frame matches the cache, so only the backstop can rebuild.
    dates_download, period_download = _readjust_downloads(monkeypatch, fresh, _adjusted(DATES).loc[DATES[-8:]])
    result = CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    pd.testing.assert_frame_equal(result, fresh, check_freq=False)
    assert _full_calls(dates_download, period_download) == 1
    metadata = json.loads((tmp_path / 'close_metadata.json').read_text())
    assert datetime.now() - datetime.fromisoformat(metadata['full_download_at']) < timedelta(minutes=5)


@REQUESTS
def test_incremental_save_keeps_full_download_time(tmp_path, monkeypatch, request_kwargs):
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(DATES))
    then = _hours_ago(100)
    _set_metadata(tmp_path, last_update=_hours_ago(1), full_download_at=then)
    dates_download, period_download = _readjust_downloads(monkeypatch, None, _adjusted(DATES).loc[DATES[-8:]])
    CachedDataFetcher(tmp_path).fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert _full_calls(dates_download, period_download) == 0
    metadata = json.loads((tmp_path / 'close_metadata.json').read_text())
    assert metadata['full_download_at'] == then
    assert datetime.now() - datetime.fromisoformat(metadata['last_update']) < timedelta(minutes=5)


@REQUESTS
def test_metadata_without_full_download_time_rebuilds_once(tmp_path, monkeypatch, request_kwargs):
    _ohlc_cache(tmp_path, monkeypatch, _adjusted(DATES))
    _set_metadata(tmp_path, last_update=_hours_ago(1), full_download_at=None)  # pre-upgrade metadata
    fresh = _adjusted(DATES)
    dates_download, period_download = _readjust_downloads(monkeypatch, fresh, fresh.loc[DATES[-8:]])
    fetcher = CachedDataFetcher(tmp_path)
    fetcher.fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert _full_calls(dates_download, period_download) == 1
    fetcher.fetch_prices(['AAA', 'BBB'], cache_name='close', **request_kwargs)
    assert _full_calls(dates_download, period_download) == 1  # then incremental
    assert dates_download.call_args.args[1] != START


@pytest.mark.parametrize('allow_stale', [True, False], ids=['stale_allowed', 'stale_disallowed'])
@REQUESTS
def test_backstop_full_download_failure(tmp_path, monkeypatch, request_kwargs, allow_stale):
    cached = _adjusted(DATES)
    _ohlc_cache(tmp_path, monkeypatch, cached)
    _set_metadata(tmp_path, last_update=_hours_ago(1), full_download_at=_hours_ago(169))
    incremental = cached.loc[DATES[-8:]].copy()
    incremental.iloc[-1] = incremental.iloc[-1] * 1.01  # final bar
    dates_download, period_download = _readjust_downloads(monkeypatch, None, incremental)
    result = CachedDataFetcher(tmp_path, allow_stale=allow_stale).fetch_prices(
        ['AAA', 'BBB'], cache_name='close', **request_kwargs)
    if allow_stale:  # previous behaviour: the incremental update
        assert len(result) == ROWS
        pd.testing.assert_frame_equal(result.loc[DATES[-1:]], incremental.loc[DATES[-1:]], check_freq=False)
        assert any(c.args[1] != START for c in dates_download.call_args_list)
    else:
        assert isinstance(result, pd.DataFrame) and result.empty
