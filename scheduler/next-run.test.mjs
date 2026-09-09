import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handoffPlan, scheduleNext, schedulerWindow } from './next-run.mjs';

const START = new Date('2026-09-09T18:00:00Z');
const current = { id: 100, created_at: START.toISOString() };
const env = { GH_TOKEN: 'test-token', GITHUB_RUN_ID: '100',
  GITHUB_REPOSITORY: 'DeanFinancials/deanfi-collectors', GITHUB_REF: 'refs/heads/main' };
const at = (minutes) => new Date(START.getTime() + minutes * 60000);

test('normal collector hands off 15 minutes after run creation', () => {
  assert.equal(handoffPlan(at(3), current, [current]).due.toISOString(), at(15).toISOString());
});

test('a quick skipped collection cannot exceed the slim runner timer budget', () => {
  assert.equal(handoffPlan(at(0), current, [current]).due.toISOString(), at(13).toISOString());
});

test('a slow or failed collection can recover immediately', () => {
  assert.equal(handoffPlan(at(20), current, [current]).due.toISOString(), at(20).toISOString());
});

test('a newer run takes ownership even when its collector is still queued', () => {
  const newer = { id: 101, created_at: at(1).toISOString(), status: 'queued' };
  assert.equal(handoffPlan(at(3), current, [newer, current]).status, 'newer-run-owns-handoff');
});

test('ties use run ID and older runs do not block handoff', () => {
  assert.equal(handoffPlan(at(3), current, [{ ...current, id: 101 }]).status,
    'newer-run-owns-handoff');
  assert.equal(handoffPlan(at(3), current, [{ ...current, id: 99 }]).status, 'schedule');
});

test('stale previous-day runs cannot restart a new session', () => {
  assert.equal(handoffPlan(new Date('2026-09-10T18:00Z'), current, []).status, 'expired-run');
});

test('weekends, daylight saving, bootstrap, and close boundaries are respected', () => {
  for (const date of ['2026-09-09T10:00Z', '2026-09-09T20:59Z',
    '2026-12-09T11:00Z', '2026-12-09T21:59Z']) {
    assert.equal(schedulerWindow(new Date(date)).active, true, date);
  }
  for (const date of ['2026-09-09T09:59Z', '2026-09-09T21:00Z',
    '2026-12-09T10:59Z', '2026-12-09T22:00Z', '2026-09-12T18:00Z']) {
    assert.equal(schedulerWindow(new Date(date)).active, false, date);
  }
});

test('a target after the close is never dispatched', () => {
  const late = { id: 100, created_at: '2026-09-09T20:52:00Z' };
  assert.equal(handoffPlan(new Date('2026-09-09T20:55Z'), late, []).status, 'session-finished');
});

function fakeApi({ newRun = false, dispatchStatus = 204 } = {}) {
  let clock = at(3);
  let reads = 0;
  const calls = [];
  return {
    calls, now: () => clock, sleep: async (ms) => { clock = new Date(+clock + ms); },
    log: () => {},
    fetchFn: async (url, options) => {
      calls.push({ url, options });
      if (url.endsWith('/runs/100')) return Response.json(current);
      if (options.method === 'POST') return new Response(null, { status: dispatchStatus });
      reads += 1;
      return Response.json({ workflow_runs: newRun && reads === 2
        ? [{ id: 101, created_at: at(10).toISOString() }, current] : [current] });
    },
  };
}

test('waits and dispatches once using native token and fixed main workflow', async () => {
  const api = fakeApi();
  const result = await scheduleNext(env, api);
  assert.equal(result.status, 'dispatched');
  const posts = api.calls.filter(({ options }) => options.method === 'POST');
  assert.equal(posts.length, 1);
  assert.match(posts[0].url, /market-data-intraday.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(posts[0].options.body), {
    ref: 'main', inputs: { source: 'handoff', scheduled_at: at(15).toISOString() },
  });
  assert.equal(posts[0].options.headers.Authorization, 'Bearer test-token');
  assert.equal(posts[0].options.redirect, 'error');
});

test('rechecks ownership after sleeping to avoid backup-trigger duplicates', async () => {
  const api = fakeApi({ newRun: true });
  assert.equal((await scheduleNext(env, api)).status, 'newer-run-owns-handoff');
  assert.equal(api.calls.filter(({ options }) => options.method === 'POST').length, 0);
});

test('surfaces dispatch rejection', async () => {
  await assert.rejects(scheduleNext(env, fakeApi({ dispatchStatus: 403 })), /HTTP 403/);
});

test('disabled chains and non-main branches never access GitHub', async () => {
  const fetchFn = () => assert.fail('unexpected API call');
  for (const change of [{ MARKET_INTRADAY_CHAIN_DISABLED: 'true' }, { GITHUB_REF: 'refs/heads/dev' }]) {
    assert.equal((await scheduleNext({ ...env, ...change }, { fetchFn })).status, 'disabled');
  }
});

test('missing permissions, malformed responses and invalid timestamps fail closed', async () => {
  await assert.rejects(scheduleNext({ ...env, GH_TOKEN: '' }, { now: () => at(3) }), /Missing/);
  await assert.rejects(scheduleNext(env, { now: () => at(3),
    fetchFn: async () => new Response(null, { status: 403 }) }), /read failed/);
  assert.throws(() => handoffPlan(at(3), { ...current, created_at: 'invalid' }, []), /Invalid/);
});
