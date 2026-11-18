"""Every job that hands a yfinance collector --cache-dir restores that dir first.

Without a restore the collector starts cold and downloads full histories for
hundreds of tickers, which is slow and invites Yahoo rate limiting. Workflows
that share a cache dir also share a key scheme, so each one can restore what
the other saved (the close run restores the day's intraday cache).
"""

import os
import re
import shlex
from itertools import permutations
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
CACHE_ACTION = re.compile(r"^actions/cache(/restore)?@")


def _cache_dirs_used(script):
    """Normalized --cache-dir paths a script passes, resolving any `cd`."""
    cwd, dirs = ".", set()
    for line in str(script).splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        if words[:1] == ["cd"] and len(words) > 1:
            cwd = os.path.normpath(os.path.join(cwd, words[1]))
        for i, word in enumerate(words[:-1]):
            if word == "--cache-dir":
                dirs.add(os.path.normpath(os.path.join(cwd, words[i + 1])))
        for word in words:
            if word.startswith("--cache-dir="):
                dirs.add(os.path.normpath(os.path.join(cwd, word.split("=", 1)[1])))
    return dirs


def _cache_paths(step):
    if not CACHE_ACTION.match(str(step.get("uses", ""))):
        return set()
    return {os.path.normpath(p.strip()) for p in str(step["with"]["path"]).splitlines() if p.strip()}


def _jobs():
    for path in WORKFLOWS:
        for name, job in yaml.safe_load(path.read_text())["jobs"].items():
            yield path.name, name, job.get("steps", [])


def _cache_users():
    return [pytest.param(steps, id=f"{wf}:{job}") for wf, job, steps in _jobs()
            if any(_cache_dirs_used(s.get("run", "")) for s in steps)]


def test_market_workflows_are_detected_as_cache_users():
    ids = {p.id for p in _cache_users()}
    assert {"market-data-intraday.yml:fetch-and-publish", "market-data-close.yml:fetch-and-publish"} <= ids


@pytest.mark.parametrize("steps", _cache_users())
def test_cache_dir_is_restored_before_first_use(steps):
    restored = set()
    for step in steps:
        missing = _cache_dirs_used(step.get("run", "")) - restored
        assert not missing, f"step {step.get('name')!r} uses {missing} before any actions/cache restore"
        restored |= _cache_paths(step)


def _render(template, date="2026-11-18", run_id="987654"):
    return (str(template).replace("${{ steps.cache_key.outputs.date }}", date)
            .replace("${{ github.run_id }}", run_id))


def _cache_steps_by_path():
    found = {}
    for wf, _, steps in _jobs():
        for step in steps:
            for path in _cache_paths(step):
                found.setdefault(path, []).append((wf, step["with"]))
    return found


def test_workflows_sharing_a_cache_dir_can_restore_each_others_saves():
    for path, users in _cache_steps_by_path().items():
        for (wf_a, a), (wf_b, b) in permutations(users, 2):
            saved_by_b = _render(b["key"], run_id="111")
            restore_keys = [_render(k) for k in str(a.get("restore-keys", "")).split() if k]
            assert any(saved_by_b.startswith(k) for k in restore_keys), (
                f"{wf_a} cannot restore the {path} cache saved by {wf_b}")
