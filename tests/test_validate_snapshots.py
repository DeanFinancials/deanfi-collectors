"""Tests for scripts/validate_snapshots.py — CI commit-time validator.

Each test builds a throwaway git repo inside tmp_path, commits a "good" version,
overwrites the working-tree file with a "bad" version, then invokes the
validator and asserts on its exit code and output.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_snapshots.py"


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(tmp_path):
    """Initialize a git repo in tmp_path with user.name/email configured."""
    _git(["init", "-b", "main"], cwd=tmp_path)
    _git(["config", "user.email", "test@example.com"], cwd=tmp_path)
    _git(["config", "user.name", "Test"], cwd=tmp_path)
    return tmp_path


def _commit_file(repo, rel_path, payload):
    fp = repo / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(payload))
    _git(["add", str(rel_path)], cwd=repo)
    _git(["commit", "-m", f"add {rel_path}"], cwd=repo)


def _write_file(repo, rel_path, payload):
    fp = repo / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(payload))


def _run_validator(repo, files):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-dir", str(repo), "--files"] + files,
        capture_output=True,
        text=True,
    )


def test_empties_out_previously_populated_data_fails(git_repo):
    path = "major-indexes/us_major_indices.json"
    _commit_file(git_repo, path, {"indices": {"^GSPC": {"price": 4500}}})
    _write_file(git_repo, path, {"indices": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 1, f"stdout={result.stdout} stderr={result.stderr}"
    combined = result.stdout + result.stderr
    assert "us_major_indices.json" in combined


def test_non_empty_new_data_passes(git_repo):
    path = "major-indexes/us_major_indices.json"
    _commit_file(git_repo, path, {"indices": {"^GSPC": {"price": 4500}}})
    _write_file(git_repo, path, {"indices": {"^GSPC": {"price": 4600}}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_head_was_already_empty_passes(git_repo):
    path = "major-indexes/us_major_indices.json"
    _commit_file(git_repo, path, {"indices": {}})
    _write_file(git_repo, path, {"indices": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_new_file_not_in_head_passes(git_repo):
    # Need at least one commit so HEAD exists
    _commit_file(git_repo, "README.md", {"unused": True})
    path = "major-indexes/us_major_indices.json"
    _write_file(git_repo, path, {"indices": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_missing_file_on_disk_skips_silently(git_repo):
    _commit_file(git_repo, "README.md", {"unused": True})
    path = "major-indexes/nonexistent.json"

    result = _run_validator(git_repo, [path])

    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert "nonexistent.json" in result.stdout


def test_unknown_body_key_skips(git_repo):
    path = "major-indexes/weird.json"
    _commit_file(git_repo, path, {"weird_key": {"x": 1}})
    _write_file(git_repo, path, {"weird_key": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_multiple_files_aggregate_failures(git_repo):
    p1 = "major-indexes/us_major_indices.json"
    p2 = "major-indexes/us_sector_indices.json"
    _commit_file(git_repo, p1, {"indices": {"^GSPC": {"price": 4500}}})
    _commit_file(git_repo, p2, {"sectors": {"XLK": {"price": 200}}})
    _write_file(git_repo, p1, {"indices": {}})
    _write_file(git_repo, p2, {"sectors": {}})

    result = _run_validator(git_repo, [p1, p2])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "us_major_indices.json" in combined
    assert "us_sector_indices.json" in combined


def test_sectors_body_key_works(git_repo):
    path = "major-indexes/us_sector_indices.json"
    _commit_file(git_repo, path, {"sectors": {"XLK": {"price": 200}}})
    _write_file(git_repo, path, {"sectors": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "sectors" in combined


def test_data_body_key_works(git_repo):
    path = "implied-volatility/vix_options_snapshot.json"
    _commit_file(git_repo, path, {"data": {"vix": 15.0}})
    _write_file(git_repo, path, {"data": {}})

    result = _run_validator(git_repo, [path])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "data" in combined
