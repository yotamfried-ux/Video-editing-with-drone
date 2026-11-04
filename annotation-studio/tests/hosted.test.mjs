// Hosted mode (Vercel + Supabase): the same Studio handler, with no long-lived process and no persistent disk.
// Proven here against real media and an S3-compatible stub that verifies pre-signed links (as R2 does):
//   only configured hosts; login code in a POST body (Secure cookie over https); long jobs complete in the request;
//   originals reach the browser through a short-lived read-only R2 link (nothing large passes the function, no secret
//   reaches the browser); opening a video probes it straight from R2; a local catalog moves once into an EMPTY
//   database, verified, and never over existing data. Each refusal asserts its specific reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';
import { CloudBucket } from '../server/cloud.mjs';
import { createApp } from '../server/app.mjs';
import { exportBackup } from '../server/backup.mjs';
import * as A from '../server/annotations.mjs';

const HOST = 'studio.example.com';
async function hosted({ withCloud = true } = {}) {
  const stub = withCloud ? await startS3Stub({ bucket: 'sportreel' }) : null;
  let video = null;
  if (stub) { video = readFileSync(makeVideo(path.join(tmp('hv-'), 'DJI_0001.mp4'), { seconds: 2, tag: 'h' })); stub.objects.set('raw/DJI_0001.mp4', { data: video }); }
  const cloud = stub ? new CloudBucket({ endpoint: stub.url, bucket: 'sportreel', accessKeyId: stub.accessKeyId, secretAccessKey: stub.secretAccessKey, retries: 0 }) : null;
  const ctx = newCtx({ cloud });
  ctx.serverless = true; ctx.allowedHosts = [HOST];
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const req = (p, { method = 'GET', host = HOST, headers = {}, body, raw } = {}) => new Promise((res, rej) => {
    const payload = raw ?? (body !== undefined ? Buffer.from(JSON.stringify(body)) : null);
    const r = http.request({ host: '127.0.0.1', port, path: p, method, headers: { host, 'x-forwarded-proto': 'https', ...(payload ? { 'content-type': 'application/json' } : {}), ...headers } }, x => {
      let d = ''; x.on('data', c => { d += c; }); x.on('end', () => { let j = null; try { j = JSON.parse(d); } catch {} res({ status: x.statusCode, headers: x.headers, json: j }); });
    });
    r.on('error', rej); if (payload) r.write(payload); r.end();
  });
  const auth = { authorization: 'Bearer test-token' };
  return { ctx, stub, video, req, auth, close: () => { server.closeAllConnections(); server.close(); stub?.close(); } };
}

test('hosted: only configured hosts; login code in a POST body sets a Secure cookie; wrong code / foreign origin refused', async () => {
  const h = await hosted({ withCloud: false });
  try {
    assert.equal((await h.req('/api/version', { host: 'evil.example.com', headers: h.auth })).status, 403, 'unknown host refused');
    assert.equal((await h.req('/api/version')).status, 401, 'no login, no data');
    const wrong = await h.req('/auth/login', { method: 'POST', body: { token: 'nope' } });
    assert.equal(wrong.status, 401); assert.match(wrong.json.message, /קוד הכניסה שגוי/);
    const foreign = await h.req('/auth/login', { method: 'POST', body: { token: 'test-token' }, headers: { origin: 'https://evil.example.com' } });
    assert.equal(foreign.status, 403);
    const ok = await h.req('/auth/login', { method: 'POST', body: { token: 'test-token' }, headers: { origin: `https://${HOST}` } });
    assert.equal(ok.status, 200);
    const c = ok.headers['set-cookie'][0];
    assert.match(c, /HttpOnly/); assert.match(c, /SameSite=Strict/); assert.match(c, /; Secure/); assert.match(c, /Max-Age=31536000/);
    const v = await h.req('/api/version', { headers: { cookie: c.split(';')[0] } });
    assert.equal(v.status, 200); assert.equal(v.json.hosted, true);
    assert.equal((await h.req('/api/backup/status', { headers: h.auth })).json.state, 'managed', 'no local backup disk in hosted mode');
  } finally { h.close(); }
});

test('hosted: jobs finish inside the request; originals go to a short-lived pre-signed R2 link that R2 accepts; R2 never written', async () => {
  const h = await hosted();
  try {
    const sync = await h.req('/api/cloud/sync', { method: 'POST', headers: { ...h.auth, origin: `https://${HOST}` } });
    assert.equal(sync.status, 200, JSON.stringify(sync.json)); assert.equal(sync.json.state, 'done', 'no polling needed');
    const obj = h.ctx.db.prepare("select id from cloud_objects where key='raw/DJI_0001.mp4'").get();
    // opening reads the MP4 header straight from R2 with byte-range reads: no ffprobe binary exists on the host
    const savedPath = process.env.PATH; process.env.PATH = '/nonexistent';
    const open = await h.req(`/api/cloud/objects/${obj.id}/open`, { method: 'POST', headers: { ...h.auth, origin: `https://${HOST}` } });
    process.env.PATH = savedPath;
    assert.equal(open.json.state, 'done', JSON.stringify(open.json));
    const sid = open.json.report.source_id;
    const src = h.ctx.db.prepare('select frame_count, fps_num, proxy_path, thumb_path, provider from sources where id=?').get(sid);
    assert.ok(src.frame_count > 0 && src.fps_num > 0, 'probed from the pre-signed link'); assert.equal(src.proxy_path, null); assert.equal(src.thumb_path, null);
    const card = await h.req(`/api/sources/${sid}`, { headers: h.auth });
    assert.equal(card.json.playback_url, `/media/${sid}/original`);
    const media = await h.req(`/media/${sid}/original`, { headers: h.auth });
    assert.equal(media.status, 302);
    const loc = new URL(media.headers.location);
    assert.equal(loc.searchParams.get('X-Amz-SignedHeaders'), 'host'); assert.equal(loc.searchParams.get('X-Amz-Expires'), '3600');
    assert.ok(!media.headers.location.includes(h.stub.secretAccessKey), 'no secret in the link');
    const fetched = await fetch(media.headers.location);
    assert.equal(fetched.status, 200); assert.equal(Buffer.from(await fetched.arrayBuffer()).equals(h.video), true, 'R2 serves the exact original');
    const tampered = new URL(media.headers.location); tampered.searchParams.set('X-Amz-Expires', '999999');
    assert.equal((await fetch(tampered)).status, 403, 'a modified link is refused');
    assert.equal((await h.req(`/media/${sid}/original`)).status, 401, 'media needs the login too');
    assert.deepEqual(h.stub.log.filter(e => !['GET', 'HEAD'].includes(e.method)), [], 'R2 only read');
  } finally { h.close(); }
});

test('hosted: a local catalog moves once into an EMPTY database (gzip, verified); a second import is refused', async () => {
  const local = newCtx();
  const ath = A.createAthlete(local.db, 'גולש מקומי');
  local.db.prepare("insert into sources(id,sha256,byte_size,display_name,frame_count,fps_num,fps_den,ingest_state,created_at,provider,cloud_key) values('s1',?,10,'DJI_X.mp4',100,30,1,'ready',?,'cloud-r2','raw/DJI_X.mp4')").run('a'.repeat(64), new Date().toISOString());
  A.saveDraft(local.db, 's1', 0, { schema: 1, segments: [seg('e1', 10, 40, { athlete_id: ath.id })], keyframes: [], reviewed_ranges: [], box_verifications: [] });
  const backup = exportBackup(local.db);
  const h = await hosted({ withCloud: false });
  try {
    const H = { ...h.auth, 'content-encoding': 'gzip', origin: `https://${HOST}` };
    const r = await h.req('/api/admin/import-backup', { method: 'POST', raw: gzipSync(Buffer.from(JSON.stringify(backup))), headers: H });
    assert.equal(r.status, 200, JSON.stringify(r.json));
    assert.equal(r.json.restored.sources, 1); assert.equal(r.json.restored.athletes, 1);
    const d = JSON.parse(h.ctx.db.prepare("select content from annotation_drafts where source_id='s1'").get().content);
    assert.equal(d.segments[0].athlete_id, ath.id, 'events and performers arrive intact');
    const again = await h.req('/api/admin/import-backup', { method: 'POST', raw: gzipSync(Buffer.from(JSON.stringify(backup))), headers: H });
    assert.equal(again.status, 409); assert.equal(again.json.code, 'IMPORT_TARGET_NOT_EMPTY');
    const junk = await h.req('/api/admin/import-backup', { method: 'POST', body: { format: 'other' }, headers: { ...h.auth, origin: `https://${HOST}` } });
    assert.equal(junk.status, 400);
    // a new event after the import gets a fresh id (sequences moved past the imported ids)
    assert.ok(A.createAthlete(h.ctx.db, 'אחרי הייבוא').id);
  } finally { h.close(); }
});
