"""Delete price cache entries no run has used recently (shared/cache_manager.py).

Runs in the market workflows after the collectors, before actions/cache saves
the cache dir at job end, so unused keys drop out of the shared cache. Best
effort: always exits 0.

Usage: python scripts/prune_price_cache.py --cache-dir ./cache [--max-unused-days 14]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    try:
        from shared.cache_manager import PRUNE_UNUSED_DAYS, prune_unused_cache

        parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        parser.add_argument("--cache-dir", required=True, help="Price cache directory")
        parser.add_argument("--max-unused-days", type=float, default=PRUNE_UNUSED_DAYS,
                            help=f"Remove entries unused for this many days (default {PRUNE_UNUSED_DAYS})")
        args = parser.parse_args(argv)
        removed = prune_unused_cache(args.cache_dir, args.max_unused_days)
        print(f"Price cache prune: removed {len(removed)} file(s) from {args.cache_dir}")
    except SystemExit as e:  # argparse: --help, or a usage error
        if e.code:
            print("Warning: price cache prune skipped (bad arguments)", file=sys.stderr)
    except Exception as e:
        print(f"Warning: price cache prune failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
