import { readFile } from 'node:fs/promises';

const NAME = 'deanfi-market-scheduler';
const CRON = '7,22,37,52 12-21 * * MON-FRI';
const required = ['CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'GITHUB_DISPATCH_TOKEN'];
for (const name of required) {
  if (!process.env[name]) throw new Error(`Required deployment secret is missing: ${name}`);
}
const base = `https://api.cloudflare.com/client/v4/accounts/${process.env.CLOUDFLARE_ACCOUNT_ID}`;
const token = process.env.CLOUDFLARE_API_TOKEN;

async function cloudflare(path, init = {}) {
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...init.headers },
    signal: AbortSignal.timeout(30000), redirect: 'error',
  });
  const body = await res.json();
  if (!res.ok || !body.success) {
    // Never log request metadata or secret bindings.
    const codes = (body.errors || []).map((err) => err.code).join(',');
    throw new Error(`Cloudflare ${path}: HTTP ${res.status}; error codes ${codes}`);
  }
  return body.result;
}

// Read-only preflight before uploading anything. A missing Workers permission
// stops here, leaving existing services and the GitHub backup schedule intact.
await cloudflare('/workers/scripts');
const github = await fetch(
  'https://api.github.com/repos/DeanFinancials/deanfi-collectors/actions/workflows/market-data-intraday.yml',
  { headers: {
    Authorization: `Bearer ${process.env.GITHUB_DISPATCH_TOKEN}`,
    Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': NAME,
  }, signal: AbortSignal.timeout(15000), redirect: 'error' },
);
if (!github.ok) throw new Error(`Scheduler token cannot access the collector: HTTP ${github.status}`);

const form = new FormData();
form.append('metadata', new Blob([JSON.stringify({
  main_module: 'worker.mjs', compatibility_date: '2026-09-09',
  bindings: [{ type: 'secret_text', name: 'GITHUB_DISPATCH_TOKEN',
    text: process.env.GITHUB_DISPATCH_TOKEN }],
  observability: { enabled: true },
})], { type: 'application/json' }));
form.append('worker.mjs', new Blob([await readFile(new URL('./worker.mjs', import.meta.url))],
  { type: 'application/javascript+module' }), 'worker.mjs');
await cloudflare(`/workers/scripts/${NAME}`, { method: 'PUT', body: form });
await cloudflare(`/workers/scripts/${NAME}/subdomain`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ enabled: false, previews_enabled: false }),
});
await cloudflare(`/workers/scripts/${NAME}/schedules`, {
  method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify([{ cron: CRON }]),
});
const schedules = await cloudflare(`/workers/scripts/${NAME}/schedules`);
if (!schedules.schedules?.some((item) => item.cron === CRON)) {
  throw new Error('Deployed schedule could not be verified');
}
console.info(`Deployed ${NAME}; verified cron ${CRON}. No public HTTP endpoint enabled.`);
