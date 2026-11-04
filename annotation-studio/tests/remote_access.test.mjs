// Permanent address through a Cloudflare Tunnel: the public host is accepted ONLY with a valid Cloudflare Access login
// (RS256 JWT checked against the team keys, audience, expiry) AND the Studio's own token; it fails closed when Access is
// not configured; any other host is refused; localhost is unaffected. Each refusal asserts its specific reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { generateKeyPairSync, createSign } from 'node:crypto';
import { newCtx } from './helpers.mjs';
import { createApp } from '../server/app.mjs';
import { remoteConfig, __resetKeyCache } from '../server/remoteaccess.mjs';

const HOST = 'studio.example.com', TEAM = 'myteam', AUD = 'aud-123';
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const other = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'k1', alg: 'RS256', use: 'sig' };
const fakeFetch = async url => { assert.equal(url, `https://${TEAM}.cloudflareaccess.com/cdn-cgi/access/certs`); return { ok: true, json: async () => ({ keys: [jwk] }) }; };
const b64u = o => Buffer.from(typeof o === 'string' ? o : JSON.stringify(o)).toString('base64url');
function jwt(claims = {}, { key = privateKey, kid = 'k1' } = {}) {
  const now = Math.floor(Date.now() / 1000);
  const h = b64u({ alg: 'RS256', kid, typ: 'JWT' }), p = b64u({ aud: [AUD], email: 'owner@example.com', iss: `https://${TEAM}.cloudflareaccess.com`, iat: now, exp: now + 600, ...claims });
  const s = createSign('RSA-SHA256').update(`${h}.${p}`).sign(key).toString('base64url');
  return `${h}.${p}.${s}`;
}
async function boot(remote) {
  __resetKeyCache();
  const ctx = newCtx(); ctx.remote = remote; ctx.accessFetch = fakeFetch;
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const req = (path, { host = HOST, headers = {}, method = 'GET', body } = {}) => new Promise((res, rej) => {
    const r = http.request({ host: '127.0.0.1', port, path, method, headers: { host, ...(body ? { 'content-type': 'application/json' } : {}), ...headers } }, x => {
      let d = ''; x.on('data', c => { d += c; }); x.on('end', () => { let j = null; try { j = JSON.parse(d); } catch {} res({ status: x.statusCode, headers: x.headers, json: j }); });
    });
    r.on('error', rej); if (body) r.write(JSON.stringify(body)); r.end();
  });
  return { req, port, close: () => { server.closeAllConnections(); server.close(); } };
}
const cfg = { host: HOST, team: TEAM, aud: AUD, ready: true };

test('public host: no / forged / wrong-audience / expired Access login is refused; another host is refused', async () => {
  const b = await boot(cfg);
  try {
    const none = await b.req('/api/version');
    assert.equal(none.status, 403); assert.match(none.json.message, /Cloudflare Access/);
    const forged = await b.req('/api/version', { headers: { 'cf-access-jwt-assertion': jwt({}, { key: other.privateKey }) } });
    assert.equal(forged.status, 403);
    const wrongAud = await b.req('/api/version', { headers: { 'cf-access-jwt-assertion': jwt({ aud: ['someone-else'] }) } });
    assert.equal(wrongAud.status, 403);
    const expired = await b.req('/api/version', { headers: { 'cf-access-jwt-assertion': jwt({ exp: Math.floor(Date.now() / 1000) - 3600 }) } });
    assert.equal(expired.status, 403);
    const evil = await b.req('/api/version', { host: 'evil.example.com', headers: { 'cf-access-jwt-assertion': jwt() } });
    assert.equal(evil.status, 403); assert.equal(evil.json.message, undefined, 'unknown host is refused before any login check');
  } finally { b.close(); }
});

test('public host with a valid Access login still needs the Studio token; the login cookie is Secure there', async () => {
  const b = await boot(cfg);
  try {
    const H = { 'cf-access-jwt-assertion': jwt() };
    const noToken = await b.req('/api/version', { headers: H });
    assert.equal(noToken.status, 401, 'Access alone is not enough: the Studio token is still required');
    const login = await b.req('/?t=test-token', { headers: H });
    assert.equal(login.status, 302);
    assert.match(login.headers['set-cookie'][0], /; Secure/);
    const cookie = login.headers['set-cookie'][0].split(';')[0];
    const ok = await b.req('/api/version', { headers: { ...H, cookie } });
    assert.equal(ok.status, 200);
    // state-changing request: the public https origin is accepted, a foreign origin is not
    const good = await b.req('/api/athletes', { method: 'POST', body: { label: 'x' }, headers: { ...H, cookie, origin: `https://${HOST}` } });
    assert.equal(good.status, 201);
    const bad = await b.req('/api/athletes', { method: 'POST', body: { label: 'y' }, headers: { ...H, cookie, origin: 'https://evil.example.com' } });
    assert.equal(bad.status, 403);
  } finally { b.close(); }
});

test('fails closed: public host configured without Access settings is refused; localhost is unaffected', async () => {
  const b = await boot({ host: HOST, team: '', aud: '', ready: false });
  try {
    const r = await b.req('/api/version', { headers: { 'cf-access-jwt-assertion': jwt() } });
    assert.equal(r.status, 403); assert.match(r.json.message, /עוד לא מוגנת/);
    const local = await b.req('/?t=test-token', { host: `127.0.0.1:${b.port}` });
    assert.equal(local.status, 302); assert.doesNotMatch(local.headers['set-cookie'][0], /Secure/, 'plain http on localhost keeps working');
  } finally { b.close(); }
  assert.equal(remoteConfig({}), null, 'not configured = local only');
  assert.throws(() => remoteConfig({ STUDIO_PUBLIC_HOST: 'https://studio.example.com/x' }), /bare host name/);
  assert.deepEqual(remoteConfig({ STUDIO_PUBLIC_HOST: 'Studio.Example.com', STUDIO_ACCESS_TEAM: 'https://myteam.cloudflareaccess.com', STUDIO_ACCESS_AUD: 'a' }),
    { host: 'studio.example.com', team: 'myteam.cloudflareaccess.com', aud: 'a', ready: true });
});
