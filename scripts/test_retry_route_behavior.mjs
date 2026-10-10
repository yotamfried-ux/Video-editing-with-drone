#!/usr/bin/env node
// Behavioural test of POST /api/operator/pipeline/retry against an in-memory
// Supabase fake and a mocked GitHub dispatch. Never touches production: the real
// route source is bundled with its `@/lib/*` imports aliased to fakes.
//
//   node scripts/test_retry_route_behavior.mjs   (needs `esbuild` resolvable)
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const esbuild = require(process.env.ESBUILD_PATH || 'esbuild');

const RUN = '61d0014a-daab-4a03-9319-69a0be691ef1';
const BATCH = 'batch_2026-10-03T12-19-52_ttgvat95';

// ---- in-memory supabase fake -------------------------------------------------
globalThis.__db = null;
globalThis.__updates = [];
class Q {
  constructor(table) { this.table = table; this.filters = []; this.patch = null; this.cols = null; }
  select(c) { this.cols = c; return this; }
  update(p) { this.patch = p; return this; }
  eq(k, v) { this.filters.push([k, v]); return this; }
  _rows() { return globalThis.__db[this.table].filter((r) => this.filters.every(([k, v]) => r[k] === v)); }
  _exec() {
    const rows = this._rows();
    if (this.patch) {
      globalThis.__updates.push({ table: this.table, patch: this.patch, n: rows.length });
      if (globalThis.__failUpdate) return { data: null, error: { message: 'boom' }, rows: [] };
      rows.forEach((r) => Object.assign(r, structuredClone(this.patch)));
    }
    return { data: null, error: null, rows: rows.map((r) => structuredClone(r)) };
  }
  single() { const { rows, error } = this._exec(); return Promise.resolve(rows.length === 1 ? { data: rows[0], error: null } : { data: null, error: error ?? { message: 'no row' } }); }
  maybeSingle() { const { rows, error } = this._exec(); return Promise.resolve({ data: rows[0] ?? null, error }); }
  then(res, rej) { const { error } = this._exec(); return Promise.resolve({ error }).then(res, rej); }
}
globalThis.__sb = { from: (t) => new Q(t) };

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'retry-route-'));
const shim = {
  'next/server': `export const NextResponse={json:(b,i)=>({status:i?.status??200,body:b})};export class NextRequest{}`,
  '@/lib/supabase-admin': `export const supabaseAdmin=globalThis.__sb;`,
  '@/lib/ratelimit': `export async function enforceRateLimit(){return globalThis.__limited??null;}`,
  '@/lib/operator-auth': `export const requireOperator=()=>globalThis.__authed!==false;`,
};
const out = path.join(tmp, 'route.mjs');
await esbuild.build({
  entryPoints: [path.join(root, 'web-api/src/app/api/operator/pipeline/retry/route.ts')],
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'error',
  plugins: [{
    name: 'alias',
    setup(b) {
      b.onResolve({ filter: /^(next\/server|@\/lib\/(supabase-admin|ratelimit|operator-auth))$/ }, (a) => ({ path: a.path, namespace: 'shim' }));
      b.onLoad({ filter: /.*/, namespace: 'shim' }, (a) => ({ contents: shim[a.path], loader: 'js' }));
      b.onResolve({ filter: /^@\// }, (a) => {
        const base = path.join(root, 'web-api/src', a.path.slice(2));
        const hit = ['.ts', '.tsx', '/index.ts'].map((e) => base + e).find((p) => fs.existsSync(p));
        return { path: hit };
      });
    },
  }],
});
const { POST } = await import(pathToFileURL(out).href);

// ---- fixtures ------------------------------------------------------------------
const manifest = () => Array.from({ length: 24 }, (_, i) => ({
  upload_id: `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`,
  storage_key: `raw/${BATCH}/f${i}.MP4`, source_filename: `f${i}.MP4`,
  source_size_bytes: 100 + i, verified_size_bytes: 100 + i, verified_at: '2026-10-03T12:34:03.043097+00:00',
}));
function seed(over = {}) {
  const m = manifest();
  globalThis.__db = {
    pipeline_runs: [{ id: RUN, status: 'failed', stage: 'publishable_business_gate_failed', input_files: m, meta: { x: 1 }, ...over.run }],
    upload_batches: [{ batch_id: BATCH, state: 'failed', pipeline_run_id: RUN, expected_file_count: 24, input_manifest: structuredClone(m), ...over.batch }],
  };
  globalThis.__updates = []; globalThis.__failUpdate = false; globalThis.__authed = true; globalThis.__limited = null;
}
const req = (body) => ({ json: async () => body });
const good = { pipeline_run_id: RUN, batch_id: BATCH };
let dispatches; let fetchImpl;
globalThis.fetch = async (url, init) => { dispatches.push({ url, init }); return fetchImpl(); };
const ok204 = () => ({ status: 204, text: async () => '' });
const call = async (body = good, { fetchFn = ok204 } = {}) => { dispatches = []; fetchImpl = fetchFn; return POST(req(body)); };
process.env.GITHUB_DISPATCH_TOKEN = 'test-token'; process.env.GITHUB_REPO = 'o/r';

const cases = [];
const t = (name, fn) => cases.push([name, fn]);

t('valid failed run + matching frozen manifest is accepted; dispatch preserves ids, reset=false, full_clean=false', async () => {
  seed(); const r = await call();
  assert.equal(r.status, 200); assert.equal(r.body.pipeline_run_id, RUN); assert.equal(r.body.batch_id, BATCH);
  assert.equal(dispatches.length, 1);
  const d = JSON.parse(dispatches[0].init.body);
  assert.deepEqual(d.inputs, { reset: 'false', full_clean: 'false', pipeline_run_id: RUN, batch_id: BATCH });
  assert.match(dispatches[0].url, /pipeline-run\.yml\/dispatches$/);
  const run = globalThis.__db.pipeline_runs[0];
  assert.equal(run.id, RUN); assert.equal(run.status, 'queued');
  assert.equal(run.meta.reset, false); assert.equal(run.meta.full_clean, false);
  assert.equal(globalThis.__db.pipeline_runs.length, 1, 'no duplicate run');
  assert.equal(globalThis.__db.upload_batches.length, 1, 'no new batch');
  assert.equal(run.input_files.length, 24, 'frozen inputs untouched');
  assert.equal(globalThis.__updates.every((u) => u.table === 'pipeline_runs'), true, 'only pipeline_runs written');
});
t('empty batch manifest (the legacy defect) is rejected before any write or dispatch', async () => {
  seed({ batch: { input_manifest: [] } }); const r = await call();
  assert.equal(r.status, 409); assert.match(r.body.error, /manifest does not match/);
  assert.equal(dispatches.length, 0); assert.equal(globalThis.__updates.length, 0);
});
t('incomplete manifest rejected', async () => {
  seed({ batch: { input_manifest: manifest().slice(0, 23) } }); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('same entries in different order rejected', async () => {
  seed({ batch: { input_manifest: manifest().reverse() } }); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('mismatched entry rejected', async () => {
  const m = manifest(); m[5].verified_size_bytes += 1; seed({ batch: { input_manifest: m } });
  assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('run with empty frozen inputs rejected', async () => {
  seed({ run: { input_files: [] }, batch: { input_manifest: [] } }); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('expected_file_count mismatch rejected', async () => {
  seed({ batch: { expected_file_count: 32 } }); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('batch locked to a different run (ambiguous ownership) rejected', async () => {
  seed({ batch: { pipeline_run_id: '11111111-1111-4111-8111-111111111111' } }); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('batch not in failed state rejected (e.g. ready/running)', async () => {
  for (const state of ['ready', 'running', 'uploading']) { seed({ batch: { state } }); assert.equal((await call()).status, 409, state); assert.equal(dispatches.length, 0); }
});
t('non-failed run rejected (queued/running/succeeded)', async () => {
  for (const status of ['queued', 'running', 'succeeded']) { seed({ run: { status } }); assert.equal((await call()).status, 409, status); assert.equal(dispatches.length, 0); }
});
t('missing/invalid ids rejected; unknown run/batch 404', async () => {
  seed();
  assert.equal((await call({})).status, 400);
  assert.equal((await call({ pipeline_run_id: RUN, batch_id: 'bad/../id' })).status, 400);
  assert.equal((await call({ pipeline_run_id: 'nope', batch_id: BATCH })).status, 404);
  assert.equal((await call({ pipeline_run_id: RUN, batch_id: 'other_batch' })).status, 404);
  assert.equal(dispatches.length, 0);
});
t('unauthorised and rate-limited requests never reach the database or GitHub', async () => {
  seed(); globalThis.__authed = false; assert.equal((await call()).status, 401);
  globalThis.__authed = true; globalThis.__limited = { status: 429, body: {} }; assert.equal((await call()).status, 429);
  assert.equal(dispatches.length, 0); assert.equal(globalThis.__updates.length, 0);
});
t('concurrent duplicate requests dispatch exactly once', async () => {
  seed(); dispatches = []; fetchImpl = ok204;
  const rs = await Promise.all([POST(req(good)), POST(req(good)), POST(req(good))]);
  assert.deepEqual(rs.map((r) => r.status).sort(), [200, 409, 409]); assert.equal(dispatches.length, 1);
});
t('sequential second request after success is rejected (already claimed)', async () => {
  seed(); assert.equal((await call()).status, 200); assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('GitHub rejects dispatch (403): run restored to failed, retryable, error surfaced', async () => {
  seed(); const r = await call(good, { fetchFn: async () => ({ status: 403, text: async () => 'nope' }) });
  assert.equal(r.status, 502); const run = globalThis.__db.pipeline_runs[0];
  assert.equal(run.status, 'failed'); assert.equal(run.stage, 'retry_dispatch_failed'); assert.ok(run.error);
  assert.equal((await call()).status, 200, 'can be retried after a definite dispatch failure');
});
t('ambiguous dispatch outcome (network error) keeps the claim: no rollback, no second dispatch', async () => {
  seed(); const r = await call(good, { fetchFn: async () => { throw new Error('timeout'); } });
  assert.equal(r.status, 502); assert.match(r.body.error, /outcome unknown/);
  assert.equal(globalThis.__db.pipeline_runs[0].status, 'queued');
  assert.equal((await call()).status, 409); assert.equal(dispatches.length, 0);
});
t('claim failure (DB error) does not dispatch', async () => {
  seed(); globalThis.__failUpdate = true; const r = await call(); assert.equal(r.status, 503); assert.equal(dispatches.length, 0);
});
t('missing dispatch config returns 503 before claiming the run', async () => {
  seed(); const tok = process.env.GITHUB_DISPATCH_TOKEN; delete process.env.GITHUB_DISPATCH_TOKEN;
  const r = await call(); process.env.GITHUB_DISPATCH_TOKEN = tok;
  assert.equal(r.status, 503); assert.equal(globalThis.__db.pipeline_runs[0].status, 'failed'); assert.equal(globalThis.__updates.length, 0);
});

let failed = 0;
for (const [name, fn] of cases) {
  try { await fn(); console.log(`ok   ${name}`); } catch (e) { failed++; console.log(`FAIL ${name}\n${e.stack}`); }
}
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`${cases.length - failed}/${cases.length} passed`);
process.exit(failed ? 1 : 0);
