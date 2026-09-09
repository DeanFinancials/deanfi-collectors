"""Retry helper for yfinance calls that hit Yahoo's HTTP 429 rate limiter.

We duck-type the exception by class-name substring ("RateLimit") and message
substring ("429") rather than importing yfinance.exceptions.YFRateLimitError
because that import path has shifted across yfinance versions and is not
guaranteed stable. This keeps the helper resilient with no hard dep.
"""

from __future__ import annotations

import time


def _is_rate_limit(exc: BaseException) -> bool:
    if "RateLimit" in type(exc).__name__:
        return True
    if "429" in str(exc):
        return True
    return False


def with_429_retry(fn, *args, retries: int = 1, sleep_seconds: float = 30.0,
                   retry_empty: bool = False, **kwargs):
    """Call fn(*args, **kwargs); retry on rate-limit errors.

    Retries up to `retries` additional times when fn raises an exception whose
    class name contains "RateLimit" or whose str() contains "429". Sleeps
    `sleep_seconds` between attempts. Re-raises after the final attempt.
    Non-rate-limit exceptions are re-raised immediately.
    With retry_empty=True, also retry missing, empty, or all-null DataFrames:
    yf.download can swallow YFRateLimitError and return these instead of raising.
    Exhausted empty responses are returned for the caller's data quality guard.
    """
    attempt = 0
    while True:
        try:
            result = fn(*args, **kwargs)
            empty = result is None or getattr(result, 'empty', False)
            if retry_empty and not empty and hasattr(result, 'dropna'):
                empty = result.dropna(how='all').empty
            if not retry_empty or not empty or attempt >= retries:
                return result
            attempt += 1
            print(f"Empty Yahoo response, sleeping {sleep_seconds}s before retry {attempt}/{retries}...")
            time.sleep(sleep_seconds)
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise
            if attempt >= retries:
                raise
            attempt += 1
            print(
                f"⏳ rate-limited, sleeping {sleep_seconds}s before retry "
                f"{attempt}/{retries}..."
            )
            time.sleep(sleep_seconds)
