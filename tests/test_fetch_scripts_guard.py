"""Structural tests verifying the assert_enough_succeeded guard is wired
into all 9 fetch_*.py scripts identified in INCIDENT-2026-05-20.

We use a structural test (read source as text, verify call patterns) instead
of an integration test because the fetch_*.py modules import pandas,
yfinance, and other heavy dependencies at module-import time, and several
of them rely on a sibling `utils.py` whose own imports vary by package.
Each unit-level guarantee about the guard itself is covered by
tests/test_fetch_guard.py; this file only verifies that each script
actually wires the guard into every applicable save site.

Contract for each listed script:
  1. It imports `assert_enough_succeeded` from `shared.fetch_guard`.
  2. Every `save_json(` (or `json.dump(` for impliedvol) call that
     persists a per-ticker output is preceded by an
     `assert_enough_succeeded(` call within a reasonable number of
     source lines.

If this test fails after someone adds a new per-ticker `save_json` call,
either guard the new call or add it to the explicit allow-list at the
top of the offending file (the bulk ETF prices guard exception is
already commented in fetch_us_major.py).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# (path-relative-to-repo-root, save-call-regex, expected_guarded_save_count)
# expected_guarded_save_count is how many save sites in the file should be
# preceded by a guard. fetch_us_major.py has 3 save_json sites but only
# 2 are guarded (the ETF bulk download is intentionally excluded).
SCRIPTS = [
    ("majorindexes/fetch_us_major.py",       r"\bsave_json\(",  2),
    ("majorindexes/fetch_sectors.py",        r"\bsave_json\(",  2),
    ("majorindexes/fetch_growth_value.py",   r"\bsave_json\(",  2),
    ("majorindexes/fetch_international.py",  r"\bsave_json\(",  2),
    ("majorindexes/fetch_bonds.py",          r"\bsave_json\(",  2),
    ("majorindexes/fetch_commodities.py",    r"\bsave_json\(",  2),
    ("impliedvol/fetch_vix_options.py",      r"\bjson\.dump\(", 1),
    ("impliedvol/fetch_major_indices_iv.py", r"\bjson\.dump\(", 1),
    ("meanreversion/fetch_price_vs_ma.py",   r"\bsave_json\(",  2),
]

# How many source lines before a save_json call we accept as "the guard
# protects this save". The actual wired pattern is 5 lines
# (assert_enough_succeeded + 3 kwarg lines + closing paren), so 10 is
# generous without being so loose it lets ungated saves slip through.
GUARD_PROXIMITY_LINES = 10

GUARD_CALL_RE = re.compile(r"\bassert_enough_succeeded\(")
IMPORT_RE = re.compile(
    r"from\s+shared\.fetch_guard\s+import\s+assert_enough_succeeded"
)


@pytest.mark.parametrize("rel_path,save_pattern,expected_guarded", SCRIPTS)
def test_script_imports_guard(rel_path, save_pattern, expected_guarded):
    """Every listed script must import the guard helper."""
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert IMPORT_RE.search(source), (
        f"{rel_path}: missing `from shared.fetch_guard import "
        f"assert_enough_succeeded` import."
    )


@pytest.mark.parametrize("rel_path,save_pattern,expected_guarded", SCRIPTS)
def test_save_calls_are_guarded(rel_path, save_pattern, expected_guarded):
    """Every applicable persistence call must be preceded by a guard call
    within GUARD_PROXIMITY_LINES source lines."""
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    save_re = re.compile(save_pattern)

    guarded = 0
    save_sites: list[int] = []
    for i, line in enumerate(lines):
        if save_re.search(line):
            save_sites.append(i + 1)  # 1-indexed for human-readable errors
            window_start = max(0, i - GUARD_PROXIMITY_LINES)
            window = "\n".join(lines[window_start:i])
            if GUARD_CALL_RE.search(window):
                guarded += 1

    assert guarded >= expected_guarded, (
        f"{rel_path}: expected at least {expected_guarded} guarded save "
        f"calls, found {guarded}. Save call lines: {save_sites}. "
        f"Each guarded save must have `assert_enough_succeeded(...)` "
        f"within {GUARD_PROXIMITY_LINES} lines above it."
    )
