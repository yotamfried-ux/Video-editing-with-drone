// API + security boundary tests (spec §16.2, acceptance #6).
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import { createApp } from '../server/app.mjs';

async function boot() {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'));
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = (p, o = {}) => fetch(base + p, { ...o, headers: { authorization: 'Bearer test-token', 'content-type': 'application/json', ...(o.headers ?? {}) } });
  return { ctx, server, base, call, id: ctx.db.prepare('select id from sources').get().id, close: () => { server.closeAllConnections(); server.close(); } };
}

test('every /api and /media route rejects missing or wrong credentials', async () => {
  const b = await boot();
  for (const p of ['/api/sources', `/api/sources/${b.id}`, '/api/athletes', '/api/datasets', '/api/audit', `/media/${b.id}/original`, `/media/${b.id}/proxy`]) {
    assert.equal((await fetch(b.base + p)).status, 401, p);
    assert.equal((await fetch(b.base + p, { headers: { authorization: 'Bearer wrong' } })).status, 401, p);
  }
  assert.equal((await fetch(b.base + '/api/sources', { method: 'POST' })).status, 401);
  assert.equal((await b.call('/api/health')).status, 200);
  b.close();
});

test('launch URL sets an HttpOnly SameSite cookie; wrong token does not', async () => {
  const b = await boot();
  const ok = await fetch(`${b.base}/?t=test-token`, { redirect: 'manual' });
  assert.equal(ok.status, 302); const ck = ok.headers.get('set-cookie'); assert.match(ck, /HttpOnly/); assert.match(ck, /SameSite=Strict/);
  const bad = await fetch(`${b.base}/?t=nope`, { redirect: 'manual' }); assert.equal(bad.headers.get('set-cookie'), null);
  assert.equal((await fetch(b.base + '/api/sources', { headers: { cookie: ck.split(';')[0] } })).status, 200);
  b.close();
});

test('DNS-rebinding and cross-origin writes are refused', async () => {
  const b = await boot();
  const status = await new Promise((res, rej) => {
    const rq = http.request({ host: '127.0.0.1', port: b.server.address().port, path: '/api/health', headers: { host: 'evil.example.com', authorization: 'Bearer test-token' } }, r => { r.resume(); res(r.statusCode); });
    rq.on('error', rej); rq.end();
  });
  assert.equal(status, 403, 'Host header must be localhost');
  const x = await b.call('/api/athletes', { method: 'POST', body: JSON.stringify({ label: 'x' }), headers: { origin: 'https://evil.example.com' } });
  assert.equal(x.status, 403);
  b.close();
});

test('draft/approve over HTTP: VERSION_CONFLICT, Hebrew message, no internals leaked', async () => {
  const b = await boot();
  const content = { schema: 1, segments: [seg('s', 3, 33)], keyframes: [], reviewed_ranges: [] };
  const put = (v, c = content) => b.call(`/api/sources/${b.id}/draft`, { method: 'PUT', body: JSON.stringify({ expected_version: v, content: c }) });
  assert.equal((await put(0)).status, 200);
  const stale = await put(0); assert.equal(stale.status, 409);
  const j = await stale.json(); assert.equal(j.code, 'VERSION_CONFLICT'); assert.match(j.message, /טען|עודכנה/);
  const bad = await put(1, { ...content, segments: [seg('s', 9, 9)] }); assert.equal((await bad.json()).code, 'INVALID_INTERVAL');
  const ap = await b.call(`/api/sources/${b.id}/approve`, { method: 'POST', body: JSON.stringify({ expected_version: 1, acknowledge_unresolved: true }) });
  assert.equal((await ap.json()).revision.seq, 1);
  const txt = JSON.stringify(await (await b.call(`/api/sources/${b.id}`)).json());
  assert.ok(!txt.includes(b.ctx.home), 'home path not exposed as a field'); assert.ok(!txt.includes('test-token'));
  b.close();
});

test('media supports byte ranges (needed for scrubbing) and 416 on bad ranges', async () => {
  const b = await boot();
  const r = await b.call(`/media/${b.id}/proxy`, { headers: { range: 'bytes=0-99' } });
  assert.equal(r.status, 206); assert.equal((await r.arrayBuffer()).byteLength, 100); assert.match(r.headers.get('content-range'), /^bytes 0-99\//);
  assert.equal((await b.call(`/media/${b.id}/proxy`, { headers: { range: 'bytes=999999999-' } })).status, 416);
  b.close();
});

test('catalog pagination and filters', async () => {
  const b = await boot();
  const all = await (await b.call('/api/sources?limit=1')).json(); assert.equal(all.items.length, 1); assert.equal(all.totals.not_annotated, 1);
  assert.equal((await (await b.call('/api/sources?status=approved')).json()).items.length, 0);
  assert.equal((await (await b.call('/api/sources?q=a.mp4')).json()).items.length, 1);
  b.close();
});

test('reconcile endpoint is async and idempotent', async () => {
  const b = await boot();
  const j = await (await b.call('/api/ingestion/reconcile', { method: 'POST', body: '{}' })).json();
  let st; for (let i = 0; i < 50; i++) { st = await (await b.call(`/api/jobs/${j.job_id}`)).json(); if (st.state !== 'running') break; await new Promise(r => setTimeout(r, 50)); }
  assert.equal(st.state, 'done'); b.close();
});

// ---- isolation from the production pipeline (spec §3, acceptance #6) ----
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
function* files(dir) {
  for (const n of readdirSync(dir)) {
    if (['node_modules', '.git', '__pycache__', '.next', 'annotation-studio'].includes(n)) continue;
    const p = path.join(dir, n), st = statSync(p);
    if (st.isDirectory()) yield* files(p);
    else if (/\.(py|ts|tsx|mjs|js|sh|yml|yaml|json|sql)$/.test(n) && st.size < 2e6) yield p;
  }
}
test('production code and workflows never reference the Studio, its state, or its credentials', () => {
  const offenders = [];
  for (const f of files(REPO)) {
    const rel = path.relative(REPO, f);
    if (rel.startsWith('docs/') || rel === '.github/workflows/annotation-studio-check.yml') continue;
    const t = readFileSync(f, 'utf8');
    if (/annotation-studio|STUDIO_HOME|STUDIO_TOKEN|studio\.sqlite/.test(t)) offenders.push(rel);
  }
  assert.deepEqual(offenders, []);
});

test('Studio code never imports from or reads pipeline/web-api secrets', () => {
  const here = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const bad = [];
  for (const d of ['server', 'web', 'scripts']) for (const f of files2(path.join(here, d))) {
    const t = readFileSync(f, 'utf8');
    if (/OPERATOR_SECRET|SUPABASE_SERVICE_KEY|GOOGLE_SERVICE_ACCOUNT|R2_SECRET|from ['"]\.\.\/\.\.\//.test(t)) bad.push(path.relative(here, f));
  }
  assert.deepEqual(bad, []);
});
function* files2(dir) { for (const n of readdirSync(dir)) { const p = path.join(dir, n); if (statSync(p).isDirectory()) yield* files2(p); else yield p; } }
