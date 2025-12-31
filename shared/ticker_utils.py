"""shared.ticker_utils

Utilities for consistent ticker normalization across collectors.

We normalize to an internal canonical form so that different upstream sources
(Yahoo, Alpaca, SEC/EDGAR, broker exports) can be looked up consistently.

Canonical form rules (current):
- Uppercase
- Strip whitespace
- Convert '.' and '/' share-class separators to '-'

Examples:
- 'brk.b' -> 'BRK-B'
- 'BF/B'  -> 'BF-B'
- 'BRK/A' -> 'BRK-A'
"""

from __future__ import annotations

from typing import Iterable, List


def normalize_ticker(ticker: str) -> str:
    if ticker is None:
        return ""

    t = str(ticker).strip().upper()
    if not t:
        return ""

    # Normalize common share-class separators
    t = t.replace(".", "-").replace("/", "-")

    # Collapse repeated separators (defensive)
    while "--" in t:
        t = t.replace("--", "-")

    return t


def candidate_tickers(ticker: str) -> List[str]:
    """Return a prioritized list of candidate normalized tickers for lookup.

    This helps when one share class is present in a source-of-truth file while
    another is used in data feeds (e.g., BRK-A vs BRK-B).
    """

    primary = normalize_ticker(ticker)
    if not primary:
        return []

    candidates: List[str] = [primary]

    # Share-class fallback: if ticker looks like ABCD-A, try ABCD-B/C and vice versa.
    if "-" in primary:
        base, suffix = primary.rsplit("-", 1)
        if len(suffix) == 1 and suffix in {"A", "B", "C"}:
            for alt_suffix in ("A", "B", "C"):
                alt = f"{base}-{alt_suffix}"
                if alt not in candidates:
                    candidates.append(alt)

    return candidates


def first_non_empty(values: Iterable[str | None]) -> str | None:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None
