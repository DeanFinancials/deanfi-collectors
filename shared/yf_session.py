"""Shared yfinance session factory.

Returns a curl_cffi-backed requests-compatible session that impersonates a real
Chrome browser, materially improving success rate against Yahoo Finance bot
detection (per INCIDENT-2026-05-20). Falls back to None when curl_cffi is not
importable; yfinance accepts session=None and will use its default transport.
"""

from __future__ import annotations


def make_session():
    """Return an impersonating curl_cffi Session, or None if unavailable."""
    try:
        from curl_cffi import requests as cffi_requests
        return cffi_requests.Session(impersonate="chrome")
    except Exception:
        return None
