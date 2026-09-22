"""Publish a validated market batch without rebasing generated JSON conflicts."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SECTIONS = ('advance-decline', 'major-indexes', 'meanreversion', 'implied-volatility')
FRESHNESS = 'data_freshness.json'
VALIDATOR = Path(__file__).with_name('validate_snapshots.py')


def git(repo, *args, check=True):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True,
                          text=True, check=check)


def freshness_at(repo, ref):
    exists = git(repo, 'ls-tree', '--name-only', ref, '--', FRESHNESS).stdout.strip()
    return json.loads(git(repo, 'show', f'{ref}:{FRESHNESS}').stdout) if exists else {}


def publish(repo, message, attempts=3):
    repo = Path(repo).resolve()
    base = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    paths = git(repo, 'diff', '--cached', '--name-only', '-z').stdout.strip('\0').split('\0')
    if paths == ['']:
        print('No market data changes to commit')
        return 'unchanged'
    if any(path != FRESHNESS and path.split('/')[0] not in SECTIONS for path in paths):
        raise ValueError('Only market outputs and their freshness may be staged')
    payloads = {path: git(repo, 'show', f':{path}').stdout for path in paths}
    local_freshness = json.loads(payloads[FRESHNESS])
    base_freshness = freshness_at(repo, base)

    for attempt in range(attempts):
        git(repo, 'fetch', 'origin', 'main')
        remote = git(repo, 'rev-parse', 'FETCH_HEAD').stdout.strip()
        git(repo, 'merge-base', '--is-ancestor', base, remote)
        changed = git(repo, 'diff', '--name-only', base, remote, '--', *SECTIONS).stdout
        remote_freshness = freshness_at(repo, remote)
        section_changed = any(
            base_freshness.get('sections', {}).get(section)
            != remote_freshness.get('sections', {}).get(section)
            for section in SECTIONS
        )
        # A correction or another market batch landed after our checkout. Keep
        # that entire batch intact, including history and freshness; the next
        # scheduled collection will use its new baseline.
        if changed.strip() or section_changed:
            print('::notice::Market data changed during collection; keeping the remote '
                  'batch and its freshness. Deferring this batch to the next collection.')
            return 'superseded'

        with tempfile.TemporaryDirectory(prefix='market-publish-') as temp:
            worktree = Path(temp) / 'data'
            git(repo, 'worktree', 'add', '--detach', str(worktree), remote)
            try:
                for path, content in payloads.items():
                    if path != FRESHNESS:
                        target = worktree / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content)
                for section in SECTIONS:
                    remote_freshness.setdefault('sections', {})[section] = local_freshness['sections'][section]
                (worktree / FRESHNESS).write_text(json.dumps(remote_freshness, indent=2) + '\n')
                subprocess.run([sys.executable, str(VALIDATOR), '--repo-dir', str(worktree)], check=True)
                git(worktree, 'add', '--', *paths)
                if git(worktree, 'diff', '--cached', '--quiet', check=False).returncode == 0:
                    return 'unchanged'
                git(worktree, 'commit', '-m', message)
                pushed = git(worktree, 'push', 'origin', 'HEAD:refs/heads/main', check=False)
                if pushed.returncode == 0:
                    print(pushed.stderr.strip())
                    return 'published'
                # Only concurrent branch movement is retryable. Auth, hooks,
                # network failures and other errors must still fail the job.
                if not any(reason in pushed.stderr for reason in ('(fetch first)', '(non-fast-forward)')):
                    raise RuntimeError(pushed.stderr)
                print(f'Remote advanced during publication; retrying ({attempt + 1}/{attempts})')
            finally:
                git(repo, 'worktree', 'remove', '--force', str(worktree))
    raise RuntimeError('Market publication exhausted retries because main kept advancing')


if __name__ == '__main__':
    publish(Path.cwd(), sys.argv[1])
