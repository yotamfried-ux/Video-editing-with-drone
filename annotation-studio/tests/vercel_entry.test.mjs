// The Vercel entry (api/index.js): missing configuration and unreachable databases give a clear 503 without secrets;
// with several candidate URLs the first that connects is used. The real-database leg runs on the PostgreSQL backend.
import test from 'node:test';
import assert from 'node:assert/strict';
import { BACKEND, pgUrlForFreshSchema } from './helpers.mjs';

function call(handler, path = '/api/version', headers = {}) {
  return new Promise(resolve => {
    const res = { status: 0, headers: {}, body: '', writeHead(s, h) { this.status = s; Object.assign(this.headers, h ?? {}); return this; }, setHeader(k, v) { this.headers[k] = v; },
      end(b) { this.body = String(b ?? ''); resolve(this); }, getHeader() {} };
    handler({ url: path, method: 'GET', headers: { host: 'studio.example.com', ...headers }, [Symbol.asyncIterator]: async function* () {} }, res);
  });
}

test('vercel entry: missing settings and an unreachable database → 503 with the reason, never a password', async () => {
  delete process.env.STUDIO_TOKEN; process.env.STUDIO_ALLOWED_HOSTS = 'studio.example.com'; process.env.STUDIO_SERVERLESS = '1';
  const { default: handler } = await import('../api/index.js');
  let r = await call(handler);
  assert.equal(r.status, 503); assert.equal(JSON.parse(r.body).code, 'CONFIG');
  process.env.STUDIO_TOKEN = 'entry-token';
  process.env.STUDIO_DB_URL = 'postgres://gt_studio.x:S3cretPassw0rd@127.0.0.1:1/postgres';
  r = await call(handler);
  const j = JSON.parse(r.body);
  assert.equal(r.status, 503); assert.equal(j.code, 'DB_UNAVAILABLE');
  assert.ok(!r.body.includes('S3cretPassw0rd'), 'the password never appears in the response');
  if (BACKEND !== 'postgres') return;
  // first candidate unreachable, second is the real database: the entry falls through to it
  process.env.STUDIO_DB_URL = `postgres://nobody:x@127.0.0.1:1/postgres | ${pgUrlForFreshSchema()}`;
  r = await call(handler, '/api/version', { authorization: 'Bearer entry-token' });
  assert.equal(r.status, 200, r.body); assert.equal(JSON.parse(r.body).hosted, true);
});
