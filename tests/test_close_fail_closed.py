"""The close run must fail rather than publish intraday or stale prices.

market-data-close.yml restores the intraday price cache, whose last bar can be
a partial intraday bar. With PRICE_CACHE_ALLOW_STALE=false a failed refresh
returns nothing, so the collector raises and writes no file.
"""

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / '.github' / 'workflows'
ENV = 'PRICE_CACHE_ALLOW_STALE'

try:
    import pyarrow  # noqa: F401
except ImportError:  # pragma: no cover - environment-dependent
    pyarrow = None

needs_parquet = pytest.mark.skipif(
    pyarrow is None, reason="pyarrow (requirements.txt) is needed for the parquet cache")


def _ohlcv(dates, tickers):
    rng = np.random.default_rng(0)
    close = pd.DataFrame(100 + rng.normal(0, 1, (len(dates), len(tickers))).cumsum(axis=0),
                         index=dates, columns=tickers)
    fields = {'Close': close, 'High': close + 1, 'Low': close - 1, 'Open': close,
              'Volume': close * 0 + 1_000_000}
    return pd.concat(fields, axis=1)


@pytest.fixture
def breadth(tmp_path, monkeypatch):
    """fetch_daily_breadth with a warm cache, Yahoo down, and outputs under tmp_path."""
    import yfinance as yf
    from shared import yf_retry
    from shared.cache_manager import CachedDataFetcher

    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(yf_retry.time, 'sleep', lambda s: None)
    tickers = ['AAA', 'BBB', 'CCC']
    cache_dir = tmp_path / 'cache'
    # Intraday left a fresh cache whose last row is today's partial bar.
    monkeypatch.setattr(yf, 'download', Mock(return_value=_ohlcv(
        pd.bdate_range(end='2026-11-18', periods=300), tickers)))
    CachedDataFetcher(cache_dir).fetch_prices(tickers, period='2y', cache_name='spx_daily_breadth')
    # Now every Yahoo download fails (rate limited: empty frames).
    yahoo = Mock(return_value=pd.DataFrame())
    monkeypatch.setattr(yf, 'download', yahoo)

    script_dir = tmp_path / 'advancedecline'
    script_dir.mkdir()
    shutil.copy(REPO_ROOT / 'advancedecline' / 'config.yml', script_dir)
    spec = importlib.util.spec_from_file_location(
        'daily_breadth_close_test', REPO_ROOT / 'advancedecline' / 'fetch_daily_breadth.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__file__ = str(script_dir / 'fetch_daily_breadth.py')  # outputs land in tmp_path
    monkeypatch.setattr(module, 'fetch_spx_tickers', lambda: tickers)
    monkeypatch.setattr(module, 'load_latest_ad_line', lambda: (None, None, None))
    monkeypatch.setattr(module.time, 'sleep', lambda s: None)
    module.args = argparse.Namespace(cache_dir=str(cache_dir))
    output = script_dir / yaml.safe_load((script_dir / 'config.yml').read_text())[
        'output_files']['daily_breadth']
    return module, output, yahoo


@needs_parquet
def test_close_run_with_failed_downloads_writes_nothing(breadth, monkeypatch):
    module, output, yahoo = breadth
    monkeypatch.setenv(ENV, 'false')
    with pytest.raises(ValueError, match='no closing prices'):
        module.main()
    assert yahoo.call_count > 0
    assert not output.exists()


@needs_parquet
def test_intraday_run_with_failed_downloads_uses_stale_cache(breadth):
    module, output, _ = breadth
    module.main()
    assert output.exists()


def _job_env(path):
    doc = yaml.safe_load(path.read_text())
    return doc, {**(doc.get('env') or {})}


def _cache_dir_steps(job):
    return [s for s in job.get('steps', []) if '--cache-dir' in str(s.get('run', ''))]


def test_close_workflow_disables_stale_cache_for_every_collector_step():
    doc, wf_env = _job_env(WORKFLOWS / 'market-data-close.yml')
    checked = 0
    for job in doc['jobs'].values():
        for step in _cache_dir_steps(job):
            env = {**wf_env, **(job.get('env') or {}), **(step.get('env') or {})}
            assert str(env.get(ENV)).lower() == 'false', step.get('name')
            checked += 1
    assert checked >= 3


def test_intraday_workflow_keeps_stale_fallback():
    doc, wf_env = _job_env(WORKFLOWS / 'market-data-intraday.yml')
    assert ENV not in wf_env
    for job in doc['jobs'].values():
        assert ENV not in (job.get('env') or {})
        for step in job.get('steps', []):
            assert ENV not in (step.get('env') or {})
            assert ENV not in str(step.get('run', ''))
