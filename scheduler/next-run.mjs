import { pathToFileURL } from 'node:url';

const REPO = 'DeanFinancials/deanfi-collectors';
const WORKFLOW = 'market-data-intraday.yml';
const API = `https://api.github.com/repos/${REPO}`;
const INTERVAL_MS = 15 * 60 * 1000;
const MAX_WAIT_MS = 13 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 15000;
const MAX_ATTEMPTS = 3;
const RETRY_BACKOFF_MS = [2000, 5000];
// ubuntu-slim jobs stop at 15 minutes; never start a retry past this budget.
const RETRY_BUDGET_MS = MAX_WAIT_MS + 75 * 1000;

class TransientError extends Error {}

// Timeouts, network failures and 5xx responses are retryable; 4xx and
// malformed responses are not and fail closed.
export function isTransient(error) {
  return error instanceof TransientError
    || error?.name === 'TimeoutError' || error?.name === 'AbortError'
    || (error instanceof TypeError && /fetch failed|network/i.test(error.message));
}

export function isCollectionWindow(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit',
    year: 'numeric', month: '2-digit', day: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(({ type, value }) => [type, value]));
  return !['Sat', 'Sun'].includes(parts.weekday)
    && Number(parts.hour) >= 8 && Number(parts.hour) < 17;
}

export function handoffPlan(now, current, runs) {
  const created = new Date(current.created_at);
  if (!Number.isFinite(created.getTime())) throw new Error('Invalid current run timestamp');
  if (runs.some((run) => String(run.id) !== String(current.id)
    && (Date.parse(run.created_at) > created.getTime()
      || (run.created_at === current.created_at && Number(run.id) > Number(current.id))))) {
    return { status: 'newer-run-owns-handoff' };
  }
  const due = new Date(Math.max(now.getTime(), Math.min(
    created.getTime() + INTERVAL_MS, now.getTime() + MAX_WAIT_MS,
  )));
  return { status: 'schedule', due };
}

export async function scheduleNext(env, {
  fetchFn = fetch, now = () => new Date(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), log = console.info,
} = {}) {
  if (env.GITHUB_REF !== 'refs/heads/main' || env.MARKET_INTRADAY_CHAIN_DISABLED === 'true') {
    return { status: 'disabled' };
  }
  if (env.GITHUB_REPOSITORY !== REPO) throw new Error('Unexpected repository');
  if (!env.GH_TOKEN || !/^\d+$/.test(env.GITHUB_RUN_ID || '')) {
    throw new Error('Missing scheduler authentication or run ID');
  }
  const headers = {
    Authorization: `Bearer ${env.GH_TOKEN}`, Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'deanfi-market-handoff',
  };
  const deadline = now().getTime() + RETRY_BUDGET_MS;
  async function withRetries(label, attempt, beforeRetry = async () => null) {
    for (let tries = 1; ; tries += 1) {
      try {
        return await attempt();
      } catch (error) {
        const backoff = RETRY_BACKOFF_MS[tries - 1] ?? RETRY_BACKOFF_MS.at(-1);
        if (!isTransient(error) || tries >= MAX_ATTEMPTS
          || now().getTime() + backoff >= deadline) throw error;
        log(`${label} attempt ${tries} failed (${error.message}); retrying in ${backoff} ms`);
        await sleep(backoff);
        const early = await beforeRetry();
        if (early) return early;
      }
    }
  }
  async function get(path) {
    return withRetries('GitHub scheduler read', async () => {
      const response = await fetchFn(`${API}${path}`, {
        headers, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), redirect: 'error',
      });
      if (response.status >= 500) {
        throw new TransientError(`GitHub scheduler read failed: HTTP ${response.status}`);
      }
      if (!response.ok) throw new Error(`GitHub scheduler read failed: HTTP ${response.status}`);
      return response.json();
    });
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
  const body = JSON.stringify({ ref: 'main', inputs: {
    source: 'handoff', scheduled_at: due.toISOString(), collect_data: isCollectionWindow(now()),
  } });
  // A timed-out or 5xx dispatch may still have landed. Before retrying, re-run
  // the ownership check so a run created by that dispatch is not duplicated.
  const outcome = await withRetries('Next collector dispatch', async () => {
    const response = await fetchFn(`${API}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), redirect: 'error',
    });
    if (response.status >= 500) {
      throw new TransientError(`Next collector dispatch failed: HTTP ${response.status}`);
    }
    if (!response.ok) throw new Error(`Next collector dispatch failed: HTTP ${response.status}`);
    return null;
  }, async () => {
    const recheck = await inspect();
    return recheck.status === 'schedule' ? null : recheck;
  });
  if (outcome) return outcome;
  return { status: 'dispatched', scheduledAt: due.toISOString() };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  scheduleNext(process.env).then((result) => console.info(JSON.stringify(result))).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
