import { pathToFileURL } from 'node:url';

const REPO = 'DeanFinancials/deanfi-collectors';
const WORKFLOW = 'market-data-intraday.yml';
const API = `https://api.github.com/repos/${REPO}`;
const INTERVAL_MS = 15 * 60 * 1000;
const MAX_WAIT_MS = 13 * 60 * 1000;

export function schedulerWindow(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit',
    year: 'numeric', month: '2-digit', day: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(({ type, value }) => [type, value]));
  return {
    active: !['Sat', 'Sun'].includes(parts.weekday)
      && Number(parts.hour) >= 6 && Number(parts.hour) < 17,
    day: `${parts.year}-${parts.month}-${parts.day}`,
  };
}

export function handoffPlan(now, current, runs) {
  const window = schedulerWindow(now);
  if (!window.active) return { status: 'outside-window' };
  const created = new Date(current.created_at);
  if (!Number.isFinite(created.getTime())) throw new Error('Invalid current run timestamp');
  if (schedulerWindow(created).day !== window.day) return { status: 'expired-run' };
  if (runs.some((run) => String(run.id) !== String(current.id)
    && (Date.parse(run.created_at) > created.getTime()
      || (run.created_at === current.created_at && Number(run.id) > Number(current.id))))) {
    return { status: 'newer-run-owns-handoff' };
  }
  const due = new Date(Math.max(now.getTime(), Math.min(
    created.getTime() + INTERVAL_MS, now.getTime() + MAX_WAIT_MS,
  )));
  if (!schedulerWindow(due).active || schedulerWindow(due).day !== window.day) {
    return { status: 'session-finished' };
  }
  return { status: 'schedule', due };
}

export async function scheduleNext(env, {
  fetchFn = fetch, now = () => new Date(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), log = console.info,
} = {}) {
  if (env.GITHUB_REF !== 'refs/heads/main' || env.MARKET_INTRADAY_CHAIN_DISABLED === 'true') {
    return { status: 'disabled' };
  }
  if (!schedulerWindow(now()).active) return { status: 'outside-window' };
  if (env.GITHUB_REPOSITORY !== REPO) throw new Error('Unexpected repository');
  if (!env.GH_TOKEN || !/^\d+$/.test(env.GITHUB_RUN_ID || '')) {
    throw new Error('Missing scheduler authentication or run ID');
  }
  const headers = {
    Authorization: `Bearer ${env.GH_TOKEN}`, Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'deanfi-market-handoff',
  };
  async function get(path) {
    const response = await fetchFn(`${API}${path}`, {
      headers, signal: AbortSignal.timeout(15000), redirect: 'error',
    });
    if (!response.ok) throw new Error(`GitHub scheduler read failed: HTTP ${response.status}`);
    return response.json();
  }
  const current = await get(`/actions/runs/${env.GITHUB_RUN_ID}`);
  async function inspect() {
    const data = await get(`/actions/workflows/${WORKFLOW}/runs?branch=main&per_page=30`);
    if (!Array.isArray(data.workflow_runs)) throw new Error('Invalid workflow runs response');
    return handoffPlan(now(), current, data.workflow_runs);
  }
  let plan = await inspect();
  if (plan.status !== 'schedule') return plan;
  const due = plan.due;
  log(`Next collector target: ${due.toISOString()}`);
  while (now().getTime() < due.getTime()) {
    await sleep(Math.min(30000, due.getTime() - now().getTime()));
  }
  // Another backup or manual run may have taken ownership while we waited.
  plan = await inspect();
  if (plan.status !== 'schedule') return plan;
  const response = await fetchFn(`${API}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: 'main', inputs: {
      source: 'handoff', scheduled_at: due.toISOString(),
    } }),
    signal: AbortSignal.timeout(15000), redirect: 'error',
  });
  if (!response.ok) throw new Error(`Next collector dispatch failed: HTTP ${response.status}`);
  return { status: 'dispatched', scheduledAt: due.toISOString() };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  scheduleNext(process.env).then((result) => console.info(JSON.stringify(result))).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
