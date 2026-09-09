import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker, { tick, inCollectionWindow } from './worker.mjs';

const now = new Date('2026-09-09T18:52:00Z');
const env = { GITHUB_DISPATCH_TOKEN: 'test-token' };
const run = (status, minutesAgo) => ({ id: 123, status,
  created_at: new Date(now.getTime() - minutesAgo * 60000).toISOString() });

function api(runs = [], status = 204) {
  const calls = [];
  const fetchFn = async (url, options) => {
    calls.push({ url, options });
    return options.method === 'POST'
      ? new Response(null, { status })
      : Response.json({ workflow_runs: runs });
  };
  return { calls, fetchFn };
}

test('dispatches the fixed main workflow with a traceable source and timestamp', async () => {
  const { calls, fetchFn } = api([run('completed', 16)]);
  assert.equal((await tick(env, now, fetchFn)).status, 'dispatched');
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /market-data-intraday.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(calls[1].options.body), { ref: 'main', inputs: {
    source: 'cloudflare', scheduled_at: now.toISOString(),
  } });
  assert.equal(calls[1].options.headers.Authorization, 'Bearer test-token');
  assert.equal(calls[1].options.redirect, 'error');
});

for (const status of ['queued', 'in_progress', 'waiting', 'requested', 'pending']) {
  test(`does not add another collector when an existing run is ${status}`, async () => {
    const { calls, fetchFn } = api([run(status, 5)]);
    assert.equal((await tick(env, now, fetchFn)).status, 'already-active');
    assert.equal(calls.length, 1);
  });
}

test('does not duplicate a recent GitHub cron or manual run', async () => {
  const { calls, fetchFn } = api([run('completed', 3)]);
  assert.equal((await tick(env, now, fetchFn)).status, 'recent-run');
  assert.equal(calls.length, 1);
});

test('surfaces a stuck collector rather than accumulating more queued work', async () => {
  const { calls, fetchFn } = api([run('queued', 31)]);
  await assert.rejects(tick(env, now, fetchFn), /over 30 minutes/);
  assert.equal(calls.length, 1);
});

test('handles New York daylight saving, weekdays, and exact hour boundaries', () => {
  for (const date of ['2026-09-09T12:00Z', '2026-09-09T20:59Z',
    '2026-12-09T13:00Z', '2026-12-09T21:59Z']) {
    assert.equal(inCollectionWindow(new Date(date)), true, date);
  }
  for (const date of ['2026-09-09T11:59Z', '2026-09-09T21:00Z',
    '2026-12-09T12:59Z', '2026-12-09T22:00Z', '2026-09-12T18:00Z']) {
    assert.equal(inCollectionWindow(new Date(date)), false, date);
  }
});

test('off hours do not call GitHub', async () => {
  assert.equal((await tick({}, new Date('2026-09-12T18:00Z'), () => {
    assert.fail('Must not call GitHub on weekends');
  })).status, 'outside-window');
});

test('missing authentication and inspection errors fail closed', async () => {
  await assert.rejects(tick({}, now), /missing/);
  await assert.rejects(tick(env, now, async () => new Response(null, { status: 403 })), /HTTP 403/);
  await assert.rejects(tick(env, now, async () => Response.json({})), /Invalid/);
});

test('dispatch rejection is a scheduler failure, not a reported success', async () => {
  const { fetchFn } = api([], 403);
  await assert.rejects(tick(env, now, fetchFn), /dispatch failed: HTTP 403/);
});

test('accepts GitHub API versions returning 200 on dispatch', async () => {
  const { fetchFn } = api([], 200);
  assert.equal((await tick(env, now, fetchFn)).status, 'dispatched');
});

test('HTTP requests cannot trigger the collector', async () => {
  assert.equal((await worker.fetch()).status, 404);
});
