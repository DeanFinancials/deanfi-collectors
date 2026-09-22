import json
import subprocess

import pytest

from scripts import publish_market_data as publisher

SNAPSHOT = 'major-indexes/us_major_indices.json'


def write(repo, path, data):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data))


def commit(repo, message='update'):
    publisher.git(repo, 'add', '.')
    publisher.git(repo, 'commit', '-m', message)


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / 'remote.git'
    publisher.git(tmp_path, 'init', '--bare', '--initial-branch=main', str(remote))
    local = tmp_path / 'local'
    publisher.git(tmp_path, 'clone', str(remote), str(local))
    for key, value in [('user.name', 'Test'), ('user.email', 'test@example.com')]:
        publisher.git(local, 'config', key, value)
    write(local, SNAPSHOT, {'indices': {'SPY': {'price': 100}}})
    write(local, publisher.FRESHNESS, {'metadata': 'keep', 'sections': {
        **{section: {'last_updated': 'old'} for section in publisher.SECTIONS},
        'options-whales': {'last_updated': 'old-options'},
    }})
    commit(local, 'baseline')
    publisher.git(local, 'push', 'origin', 'main')
    other = tmp_path / 'other'
    publisher.git(tmp_path, 'clone', str(remote), str(other))
    for key, value in [('user.name', 'Test'), ('user.email', 'test@example.com')]:
        publisher.git(other, 'config', key, value)
    write(local, SNAPSHOT, {'indices': {'SPY': {'price': 101}}})
    freshness = json.loads((local / publisher.FRESHNESS).read_text())
    for section in publisher.SECTIONS:
        freshness['sections'][section] = {'last_updated': 'new-market'}
    write(local, publisher.FRESHNESS, freshness)
    publisher.git(local, 'add', '.')
    return local, other, remote


def remote_json(remote, path):
    return json.loads(publisher.git(remote, 'show', f'main:{path}').stdout)


def advance_other(other):
    write(other, 'options-whales/snapshot.json', {'value': 42})
    freshness = json.loads((other / publisher.FRESHNESS).read_text())
    freshness['sections']['options-whales'] = {'last_updated': 'new-options'}
    write(other, publisher.FRESHNESS, freshness)
    commit(other)
    publisher.git(other, 'push', 'origin', 'main')


def test_publishes_batch_without_modifying_original_checkout(repos):
    local, _, remote = repos
    base = publisher.git(local, 'rev-parse', 'HEAD').stdout
    assert publisher.publish(local, 'market') == 'published'
    assert remote_json(remote, SNAPSHOT)['indices']['SPY']['price'] == 101
    assert publisher.git(local, 'rev-parse', 'HEAD').stdout == base
    assert len(publisher.git(local, 'worktree', 'list').stdout.splitlines()) == 1


def test_preserves_unrelated_outputs_and_freshness(repos):
    local, other, remote = repos
    advance_other(other)
    assert publisher.publish(local, 'market') == 'published'
    data = remote_json(remote, publisher.FRESHNESS)
    assert data['metadata'] == 'keep'
    assert data['sections']['options-whales']['last_updated'] == 'new-options'
    assert data['sections']['major-indexes']['last_updated'] == 'new-market'
    assert remote_json(remote, 'options-whales/snapshot.json') == {'value': 42}


@pytest.mark.parametrize('path', [SNAPSHOT, 'advance-decline/ad_line_historical.json', publisher.FRESHNESS])
def test_overlapping_correction_preserves_entire_remote_batch(repos, path):
    local, other, remote = repos
    if path == publisher.FRESHNESS:
        data = json.loads((other / path).read_text())
        data['sections']['major-indexes']['last_updated'] = 'correction'
    else:
        data = {'corrected': True}
    write(other, path, data)
    commit(other, 'correction')
    publisher.git(other, 'push', 'origin', 'main')
    before = publisher.git(remote, 'rev-parse', 'main').stdout
    assert publisher.publish(local, 'market') == 'superseded'
    assert publisher.git(remote, 'rev-parse', 'main').stdout == before
    assert remote_json(remote, path) == data


def test_push_race_retries_and_preserves_other_collector(repos, monkeypatch):
    local, other, remote = repos
    original = publisher.git
    raced = False

    def race(repo, *args, **kwargs):
        nonlocal raced
        if args[:3] == ('push', 'origin', 'HEAD:refs/heads/main') and not raced:
            raced = True
            advance_other(other)
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(publisher, 'git', race)
    assert publisher.publish(local, 'market') == 'published'
    assert raced
    assert remote_json(remote, SNAPSHOT)['indices']['SPY']['price'] == 101
    assert remote_json(remote, publisher.FRESHNESS)['sections']['options-whales']['last_updated'] == 'new-options'


def test_rejected_push_is_not_reported_as_success(repos):
    local, _, remote = repos
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\necho "publication rejected" >&2\nexit 1\n')
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match='publication rejected'):
        publisher.publish(local, 'market')
    assert remote_json(remote, SNAPSHOT)['indices']['SPY']['price'] == 100


def test_invalid_snapshot_cannot_be_published(repos):
    local, _, remote = repos
    write(local, SNAPSHOT, {'indices': {}})
    publisher.git(local, 'add', SNAPSHOT)
    with pytest.raises(subprocess.CalledProcessError):
        publisher.publish(local, 'market')
    assert remote_json(remote, SNAPSHOT)['indices']['SPY']['price'] == 100
