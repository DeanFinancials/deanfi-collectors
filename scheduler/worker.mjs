const REPOSITORY = 'DeanFinancials/deanfi-collectors';
const WORKFLOW = 'market-data-intraday.yml';
const API = `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}`;
const MIN_INTERVAL_MS = 12 * 60 * 1000;

export function inCollectionWindow(now) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(now).map(({ type, value }) => [type, value]));
  return !['Sat', 'Sun'].includes(parts.weekday) && Number(parts.hour) >= 8
    && Number(parts.hour) < 17;
}

export async function tick(env, now = new Date(), fetchFn = fetch) {
  if (!inCollectionWindow(now)) return { status: 'outside-window' };
  if (!env.GITHUB_DISPATCH_TOKEN) throw new Error('GITHUB_DISPATCH_TOKEN is missing');
  const headers = {
    Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'deanfi-market-scheduler',
  };
  const response = await fetchFn(`${API}/runs?branch=main&per_page=30`, {
    headers, signal: AbortSignal.timeout(15000), redirect: 'error',
  });
  if (!response.ok) throw new Error(`Cannot inspect collector runs: HTTP ${response.status}`);
  const { workflow_runs: runs } = await response.json();
  if (!Array.isArray(runs)) throw new Error('Invalid collector run response');
  const active = runs.find((run) => run.status !== 'completed');
  if (active) {
    const age = now.getTime() - Date.parse(active.created_at);
    if (!Number.isFinite(age) || age > 30 * 60 * 1000) {
      throw new Error('Collector has been queued or active for over 30 minutes');
    }
    return { status: 'already-active', runId: active.id };
  }
  if (runs.some((run) => now.getTime() - Date.parse(run.created_at) < MIN_INTERVAL_MS)) {
    return { status: 'recent-run' };
  }
  const dispatch = await fetchFn(`${API}/dispatches`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: 'main', inputs: {
      source: 'cloudflare', scheduled_at: now.toISOString(),
    } }),
    signal: AbortSignal.timeout(15000), redirect: 'error',
  });
  if (!dispatch.ok) throw new Error(`Collector dispatch failed: HTTP ${dispatch.status}`);
  return { status: 'dispatched', scheduledAt: now.toISOString() };
}

export default {
  async scheduled(controller, env) {
    // Use current time to avoid dispatching a delayed event after market hours.
    const result = await tick(env);
    console.info(JSON.stringify({ ...result, eventTime: controller.scheduledTime }));
  },
  async fetch() {
    // No HTTP control endpoint. Only Cloudflare Cron Triggers can dispatch jobs.
    return new Response('Not found', { status: 404 });
  },
};
