"""Guard helper for fetch_*.py scripts.

Prevents a fully-failed run (0 successful tickers) from overwriting a
previously-good snapshot or historical JSON file. The rule is intentionally
binary — fail only when zero tickers succeeded — and is not a percentage
threshold.
"""
import sys


def assert_enough_succeeded(successful: int, total: int, *, label: str) -> None:
    """Exit(1) if the run produced zero successes out of a positive total.

    Args:
        successful: Number of tickers that produced usable data this run.
        total: Number of tickers attempted this run.
        label: Short identifier for the caller (e.g. "stockwhales snapshot")
            included in the stderr message.

    Behavior:
        - total == 0: no-op (nothing was attempted; nothing to guard).
        - successful == 0 and total > 0: print error to stderr, sys.exit(1).
        - otherwise: return None.
    """
    if total > 0 and successful == 0:
        # stderr (not stdout) so CI failure logs stay separable from progress output.
        print(
            f"❌ {label}: 0/{total} tickers succeeded; refusing to overwrite snapshot.",
            file=sys.stderr,
        )
        sys.exit(1)
