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
import math
import subprocess
import sys
from pathlib import Path

# Files validated by default. Mirrors snapshot files affected by the
# 2026-05-20 yfinance rate-limit incident.
# NOTE: meanreversion/price_vs_ma_snapshot.json is intentionally EXCLUDED.
# Its body shape differs (single-ticker SPY snapshot) so an empty `indices`
# dict can be a normal edge case. The Task 2 per-script guard covers it.
DEFAULT_FILES = [
    "advance-decline/daily_breadth.json",
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


def _reject_non_finite(value: str):
    raise ValueError(f"non-standard numeric constant {value}")


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
        new_payload = json.loads(
            disk_path.read_text(),
            parse_constant=_reject_non_finite,
        )
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"❌ {rel_path}: unreadable ({exc}); refusing commit"
        print(msg, file=sys.stderr)
        return msg
    except ValueError as exc:
        msg = f"❌ {rel_path}: invalid JSON ({exc})"
        print(msg, file=sys.stderr)
        return msg

    failure = _validate_observations(rel_path, new_payload)
    if failure:
        msg = f"❌ {rel_path}: {failure}; refusing commit"
        print(msg, file=sys.stderr)
        return msg

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


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_observations(rel_path, payload):
    if not isinstance(payload, dict):
        return 'snapshot must be an object'
    if rel_path == 'major-indexes/us_sector_indices.json':
        sectors = payload.get('sectors', {})
        for symbol, row in sectors.items():
            price = row.get('current_price') if isinstance(row, dict) else None
            change = row.get('daily_change_percent') if isinstance(row, dict) else None
            if not _finite_number(price) or price <= 0 or not _finite_number(change):
                return f'{symbol} has no usable sector price/return'
    if rel_path == 'advance-decline/daily_breadth.json':
        counts = payload.get('data', {}).get('advances_declines', {})
        values = [counts.get(key) for key in ('advances', 'declines', 'unchanged')]
        total = counts.get('total_stocks')
        if (not all(_finite_number(value) and value >= 0 for value in values)
                or not _finite_number(total) or total <= 0 or not 0 < sum(values) <= total):
            return 'breadth has no usable observations or inconsistent counts'
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
            f"❌ {len(failures)} file(s) failed snapshot validation; refusing commit.",
            file=sys.stderr,
        )
        return 1
    print("✅ Snapshot validator: usable observations and no empty-overwrite detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
