#!/usr/bin/env python3
"""CI commit-time validator: refuse a commit that would empty out a snapshot.

For each tracked snapshot file, compare the about-to-be-committed working-tree
version against `git show HEAD:<path>`. If HEAD has a non-empty body
(`indices`/`sectors`/`data`) and the new file's body is empty, the validator
fails the build. This is a belt-and-suspenders check behind the per-script
fetch guard.

Invoke from the data-repo checkout root (CI: data-cache/). DEFAULT_FILES paths
are relative to that root.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Files validated by default. Mirrors snapshot files affected by the
# 2026-05-20 yfinance rate-limit incident.
# NOTE: meanreversion/price_vs_ma_snapshot.json is intentionally EXCLUDED.
# Its body shape differs (single-ticker SPY snapshot) so an empty `indices`
# dict can be a normal edge case. The Task 2 per-script guard covers it.
DEFAULT_FILES = [
    "major-indexes/us_major_indices.json",
    "major-indexes/us_sector_indices.json",
    "major-indexes/us_growth_value_indices.json",
    "major-indexes/international_major_indices.json",
    "major-indexes/bond_treasury_indices.json",
    "major-indexes/commodity_indices.json",
    "implied-volatility/vix_options_snapshot.json",
    "implied-volatility/major_indices_iv_snapshot.json",
]

BODY_KEYS = ("indices", "sectors", "data")


def _find_body_key(payload):
    if not isinstance(payload, dict):
        return None
    for k in BODY_KEYS:
        if k in payload:
            return k
    return None


def _load_head_version(repo_dir: Path, rel_path: str):
    """Return parsed JSON of HEAD:<rel_path>, or None if missing/unparseable."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        capture_output=True,
        text=True,
        cwd=str(repo_dir),
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _validate_file(repo_dir: Path, rel_path: str) -> str | None:
    """Return None if OK, else a failure message string."""
    disk_path = repo_dir / rel_path
    if not disk_path.exists():
        print(f"⏭  {rel_path}: not on disk, skipping")
        return None

    try:
        new_payload = json.loads(disk_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⏭  {rel_path}: unreadable ({exc}), skipping")
        return None

    body_key = _find_body_key(new_payload)
    if body_key is None:
        print(f"⏭  {rel_path}: no known body key, skipping")
        return None

    new_body = new_payload.get(body_key)
    if isinstance(new_body, dict) and len(new_body) > 0:
        return None  # populated — fine
    if not isinstance(new_body, dict):
        return None  # not a dict body — out of scope

    # New body is an empty dict. Check HEAD.
    head_payload = _load_head_version(repo_dir, rel_path)
    if head_payload is None:
        return None  # no HEAD version (new file) — first write allowed
    head_body_key = _find_body_key(head_payload)
    if head_body_key is None:
        return None
    head_body = head_payload.get(head_body_key)
    if isinstance(head_body, dict) and len(head_body) > 0:
        msg = f"❌ {rel_path}: about to overwrite non-empty {body_key} with empty"
        # stderr so CI grep on '❌' picks both per-file detail and summary.
        print(msg, file=sys.stderr)
        return msg
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", default=None,
                        help="Paths relative to --repo-dir. Defaults to DEFAULT_FILES.")
    parser.add_argument("--repo-dir", default=".",
                        help="Repo root to resolve files and run git in.")
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).resolve()
    files = args.files if args.files else DEFAULT_FILES

    failures = []
    for rel_path in files:
        failure = _validate_file(repo_dir, rel_path)
        if failure:
            failures.append(failure)

    if failures:
        print(
            f"❌ {len(failures)} file(s) would empty out previously-populated "
            "data; refusing commit.",
            file=sys.stderr,
        )
        return 1
    print("✅ Snapshot validator: no empty-overwrite detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
