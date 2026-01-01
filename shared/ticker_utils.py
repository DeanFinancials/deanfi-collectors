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

Some companies have multiple actively-traded share tickers that do not follow
the typical share-class separator pattern (e.g., GOOG vs GOOGL). For metadata
enrichment, we treat a small set of these as equivalents so sector/industry
lookup remains consistent.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence


# Known alternate ticker pairs (not using '.' or '/' separators).
#
# We use these in two places:
# - Metadata enrichment: allow lookup to succeed when the source-of-truth file
#   only has one of the tickers.
# - Output de-duplication: collapse a company that has multiple tickers into a
#   single canonical ticker so dashboards don't double-count.
_ALTERNATE_TICKERS: dict[str, list[str]] = {
    # Alphabet
    "GOOG": ["GOOGL"],
    "GOOGL": ["GOOG"],
    # Fox
    "FOX": ["FOXA"],
    "FOXA": ["FOX"],
    # News Corp
    "NWS": ["NWSA"],
    "NWSA": ["NWS"],
}

# Canonical company ticker preference for de-duplication.
# Pick the 'A' class for FOX/FOXA and NWS/NWSA, and GOOGL for Alphabet.
_COMPANY_CANONICAL: dict[str, str] = {
    "GOOG": "GOOGL",
    "GOOGL": "GOOGL",
    "FOX": "FOXA",
    "FOXA": "FOXA",
    "NWS": "NWSA",
    "NWSA": "NWSA",
}


def canonical_company_ticker(ticker: str) -> str:
    """Return the canonical ticker to represent a company.

    For most tickers, this is simply the normalized ticker.
    For a small set of known dual-class/alternate tickers, this collapses to a
    single canonical symbol so outputs don't double-count.
    """

    t = normalize_ticker(ticker)
    return _COMPANY_CANONICAL.get(t, t)


def dedupe_company_tickers(tickers: Sequence[str]) -> List[str]:
    """Deduplicate a list of tickers at the company level.

    If both an alternate and its canonical symbol are present, keep the
    canonical symbol.
    """

    # Map canonical -> list of original tickers (normalized) seen.
    by_company: dict[str, list[str]] = {}
    for t in tickers:
        nt = normalize_ticker(t)
        if not nt:
            continue
        c = canonical_company_ticker(nt)
        by_company.setdefault(c, []).append(nt)

    # Preserve input order as much as possible while preferring canonical.
    out: List[str] = []
    seen_company: set[str] = set()
    for t in tickers:
        nt = normalize_ticker(t)
        if not nt:
            continue
        c = canonical_company_ticker(nt)
        if c in seen_company:
            continue

        # If canonical exists anywhere in the group, emit canonical.
        group = by_company.get(c, [])
        chosen = c if c in group else group[0] if group else c
        out.append(chosen)
        seen_company.add(c)

    return out


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

    # Known alternate tickers (e.g., GOOG <-> GOOGL) for enrichment lookups.
    for alt in _ALTERNATE_TICKERS.get(primary, []):
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
