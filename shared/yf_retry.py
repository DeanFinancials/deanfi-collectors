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


def with_429_retry(fn, *args, retries: int = 1, sleep_seconds: float = 30.0, **kwargs):
    """Call fn(*args, **kwargs); retry on rate-limit errors.

    Retries up to `retries` additional times when fn raises an exception whose
    class name contains "RateLimit" or whose str() contains "429". Sleeps
    `sleep_seconds` between attempts. Re-raises after the final attempt.
    Non-rate-limit exceptions are re-raised immediately.
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
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
