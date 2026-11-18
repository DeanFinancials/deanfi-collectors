"""Pruning drops price cache entries no run has used recently, and nothing else.

Cache keys change when a script's symbol set or key scheme changes; without
pruning the old parquet files ride along in the shared actions/cache forever.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import yaml

from shared.cache_manager import PRUNE_UNUSED_DAYS, USAGE_FILE, CachedDataFetcher, prune_unused_cache

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 18, 21, 30, tzinfo=timezone.utc)
MARKET_WORKFLOWS = ["market-data-intraday.yml", "market-data-close.yml"]


def _entry(cache_dir, name, *, last_update=None, last_used_at=None, parquet=True, metadata=True):
    if parquet:
        (cache_dir / f"{name}.parquet").write_bytes(b"PAR1")
    if metadata:
        payload = {"ticker_count": 1, "data_start": "2025-01-01", "data_end": "2026-11-18"}
        if last_update is not None:
            # CacheMetadata writes a naive local timestamp.
            payload["last_update"] = last_update.astimezone().replace(tzinfo=None).isoformat()
        (cache_dir / f"{name}_metadata.json").write_text(json.dumps(payload))
    if last_used_at is not None:
        usage_file = cache_dir / USAGE_FILE
        usage = json.loads(usage_file.read_text()) if usage_file.exists() else {}
        usage[name] = last_used_at.isoformat()
        usage_file.write_text(json.dumps(usage))


def test_unused_entries_and_orphan_halves_are_pruned_live_entries_kept(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    old = NOW - timedelta(days=PRUNE_UNUSED_DAYS + 1)
    recent = NOW - timedelta(days=3)
    _entry(cache, "majorindexes_fetch_us_major", last_update=old)
    _entry(cache, "meanreversion_price_vs_ma", last_update=old, last_used_at=old)
    _entry(cache, "spx_daily_breadth", last_update=recent)
    # Saved long ago but read recently (stale fallback, reuse): still live.
    _entry(cache, "majorindexes_1y_abc123", last_update=old, last_used_at=recent)
    _entry(cache, "orphan_metadata_only", last_update=recent, parquet=False)
    _entry(cache, "orphan_parquet_only", metadata=False)
    _entry(cache, "gone_long_ago", parquet=False, metadata=False, last_used_at=old)
    (cache / "notes.txt").write_text("not a cache entry")
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"PAR1")
    (tmp_path / "outside_metadata.json").write_text("{}")

    removed = prune_unused_cache(cache, now=NOW)

    assert sorted(p.name for p in cache.iterdir()) == [
        "majorindexes_1y_abc123.parquet",
        "majorindexes_1y_abc123_metadata.json",
        "notes.txt",
        USAGE_FILE,
        "spx_daily_breadth.parquet",
        "spx_daily_breadth_metadata.json",
    ]
    assert sorted(removed) == sorted([
        "majorindexes_fetch_us_major.parquet", "majorindexes_fetch_us_major_metadata.json",
        "meanreversion_price_vs_ma.parquet", "meanreversion_price_vs_ma_metadata.json",
        "orphan_metadata_only_metadata.json", "orphan_parquet_only.parquet",
    ])
    assert outside.exists() and (tmp_path / "outside_metadata.json").exists()
    # The usage record forgets entries whose files are gone.
    assert set(json.loads((cache / USAGE_FILE).read_text())) == {"majorindexes_1y_abc123"}


def test_unreadable_metadata_falls_back_to_file_age(tmp_path):
    _entry(tmp_path, "fresh_corrupt", last_update=NOW)
    (tmp_path / "fresh_corrupt_metadata.json").write_text("{not json")
    _entry(tmp_path, "old_corrupt", last_update=NOW)
    (tmp_path / "old_corrupt_metadata.json").write_text("{not json")
    stamp = (NOW - timedelta(days=PRUNE_UNUSED_DAYS + 5)).timestamp()
    os.utime(tmp_path / "old_corrupt_metadata.json", (stamp, stamp))
    os.utime(tmp_path / "fresh_corrupt_metadata.json", (NOW.timestamp(), NOW.timestamp()))

    prune_unused_cache(tmp_path, now=NOW)

    assert (tmp_path / "fresh_corrupt.parquet").exists()
    assert not (tmp_path / "old_corrupt.parquet").exists()


def test_symlinks_in_cache_dir_are_never_followed_or_removed(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    target = tmp_path / "precious.parquet"
    target.write_bytes(b"PAR1")
    (cache / "linked.parquet").symlink_to(target)

    prune_unused_cache(cache, now=NOW)

    assert (cache / "linked.parquet").is_symlink() and target.exists()


def test_errors_are_logged_not_raised(tmp_path, monkeypatch, capsys):
    assert prune_unused_cache(tmp_path / "missing", now=NOW) == []
    assert prune_unused_cache(None, now=NOW) == []

    _entry(tmp_path, "stuck", last_update=NOW - timedelta(days=60))
    monkeypatch.setattr(Path, "unlink", Mock(side_effect=PermissionError("read-only")))
    assert prune_unused_cache(tmp_path, now=NOW) == []
    assert "read-only" in capsys.readouterr().err


def test_prune_script_exits_zero_even_when_pruning_fails(tmp_path):
    script = REPO_ROOT / "scripts" / "prune_price_cache.py"
    a_file = tmp_path / "a_file"
    a_file.write_text("not a directory")
    for args in (["--cache-dir", str(tmp_path / "missing")], ["--cache-dir", str(a_file)],
                 ["--cache-dir", str(tmp_path), "--max-unused-days", "nope"]):
        result = subprocess.run([sys.executable, str(script), *args], cwd=tmp_path,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_prune_script_prunes_unused_entries(tmp_path):
    _entry(tmp_path, "gone", last_update=datetime.now(timezone.utc) - timedelta(days=60))
    _entry(tmp_path, "kept", last_update=datetime.now(timezone.utc))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "prune_price_cache.py"), "--cache-dir", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["kept.parquet", "kept_metadata.json"]


def test_a_read_without_a_save_records_use(tmp_path, monkeypatch):
    """A stale-cache fallback reads the entry without saving it; pruning must still keep it."""
    pytest.importorskip("pyarrow")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    frame = pd.DataFrame({("Close", "AAA"): [10.0, 11.0]}, index=pd.date_range("2026-09-08", periods=2))
    download = Mock(return_value=frame)
    monkeypatch.setattr(CachedDataFetcher, "_download_with_period", download)
    monkeypatch.setattr(CachedDataFetcher, "_download_with_dates", download)
    fetcher = CachedDataFetcher(tmp_path, allow_stale=True)
    fetcher.fetch_prices(["AAA"], period="2y", cache_name="live")

    # Last saved three days ago; this run's refresh fails and returns the stale cache.
    meta_path = tmp_path / "live_metadata.json"
    saved = json.loads(meta_path.read_text())
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
    saved.update(last_update=three_days_ago, full_download_at=three_days_ago)
    meta_path.write_text(json.dumps(saved))
    (tmp_path / USAGE_FILE).unlink(missing_ok=True)
    download.return_value = pd.DataFrame()
    stale = fetcher.fetch_prices(["AAA"], period="2y", cache_name="live")
    assert not stale.empty
    assert json.loads(meta_path.read_text()) == saved  # no save: the entry's files are untouched

    # Twelve days on, the save is 15 days old but the read only 12.
    prune_unused_cache(tmp_path, now=datetime.now(timezone.utc) + timedelta(days=12))
    assert (tmp_path / "live.parquet").exists() and meta_path.exists()


def _steps(workflow):
    doc = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())
    return doc["jobs"]["fetch-and-publish"]["steps"]


def _uses_cache_dir(step):
    return "--cache-dir" in str(step.get("run", ""))


def _is_prune(step):
    return "scripts/prune_price_cache.py" in str(step.get("run", ""))


@pytest.mark.parametrize("workflow", MARKET_WORKFLOWS)
def test_market_workflows_prune_after_collectors_before_the_cache_is_saved(workflow):
    steps = _steps(workflow)
    prunes = [i for i, s in enumerate(steps) if _is_prune(s)]
    assert len(prunes) == 1, f"{workflow} must run scripts/prune_price_cache.py once"
    prune = steps[prunes[0]]
    collectors = [i for i, s in enumerate(steps) if _uses_cache_dir(s) and not _is_prune(s)]
    assert collectors and prunes[0] > max(collectors), "prune must follow every collector that uses the cache"

    # actions/cache (not cache/restore) saves in its post step at job end, so a
    # prune that runs anywhere in the job lands in the saved cache.
    cache = [s for s in steps if str(s.get("uses", "")).startswith("actions/cache@")]
    assert len(cache) == 1 and not any(str(s.get("uses", "")).startswith("actions/cache/save@") for s in steps)
    assert "--cache-dir ./cache" in prune["run"] and cache[0]["with"]["path"] == "./cache"

    # Best effort: a prune problem never fails the publish, and it runs exactly
    # when the cache was restored.
    assert prune.get("continue-on-error") is True
    assert prune.get("if") == cache[0].get("if")
