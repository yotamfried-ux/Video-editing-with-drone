// Light playback copies: made on the operator's computer from the read-only originals, proven frame-for-frame,
// uploaded as NEW objects into a SEPARATE bucket (never the originals' bucket, never overwritten), and played by the
// hosted Studio instead of the heavy original when present. Each refusal asserts its specific reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { newCtx, tmp } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';
import { CloudBucket } from '../server/cloud.mjs';
import { createApp } from '../server/app.mjs';
import { previewKey, previewLookup, probeFile } from '../server/previews.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
// a 59.94 fps 1080p clip with a constant frame rate, like the DJI originals (smaller, for speed)
function original(file) {
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=60000/1001:d=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', file]);
  assert.equal(r.status, 0, String(r.stderr)); return file;
}

test('previewKey keeps the folder and names the copy next to it', () => {
  assert.equal(previewKey('processed/2026-10-04T07-38-33_DJI_20260724103751_0165_D.MP4'), 'processed/2026-10-04T07-38-33_DJI_20260724103751_0165_D.preview.mp4');
  assert.equal(previewKey('raw/a.b/c.mov'), 'raw/a.b/c.preview.mp4');
});

test('make-previews: 720p, frame for frame, uploaded only into the preview bucket; existing copy skipped; same bucket refused', async () => {
  const orig = await startS3Stub({ bucket: 'sportreel' }), prev = await startS3Stub({ bucket: 'sportreel-previews', accessKeyId: 'AKIAPREVIEW', secretAccessKey: 'preview-secret' });
  try {
    const video = readFileSync(original(path.join(tmp('pv-'), 'DJI_0001.MP4')));
    orig.objects.set('processed/DJI_0001.MP4', { data: video });
    const env = { ...process.env, STUDIO_CLOUD_R2_ENDPOINT: orig.url, STUDIO_CLOUD_R2_BUCKET: 'sportreel', STUDIO_CLOUD_R2_ACCESS_KEY_ID: orig.accessKeyId, STUDIO_CLOUD_R2_SECRET_ACCESS_KEY: orig.secretAccessKey,
      STUDIO_PREVIEW_R2_ENDPOINT: prev.url, STUDIO_PREVIEW_R2_BUCKET: 'sportreel-previews', STUDIO_PREVIEW_R2_WRITE_ACCESS_KEY_ID: 'AKIAPREVIEW', STUDIO_PREVIEW_R2_WRITE_SECRET_ACCESS_KEY: 'preview-secret', STUDIO_CLOUD_INCLUDE: 'DJI' };
    const run = (extra = {}, args = []) => new Promise(res => { const p = require_spawn(env, extra, args); let out = ''; p.stdout.on('data', d => { out += d; }); p.stderr.on('data', d => { out += d; }); p.on('close', code => res({ code, out })); });
    const r1 = await run();
    assert.equal(r1.code, 0, r1.out); assert.match(r1.out, /OK processed\/DJI_0001\.preview\.mp4/);
    const copy = prev.objects.get('processed/DJI_0001.preview.mp4');
    assert.ok(copy, 'uploaded into the preview bucket');
    const f = path.join(tmp('pv-'), 'copy.mp4'); writeFileSync(f, copy.data);
    const a = await probeFile(f);
    const src = path.join(tmp('pv-'), 'o.mp4'); writeFileSync(src, video);
    const po = await probeFile(src);
    assert.equal(a.frame_count, po.frame_count, 'same number of frames'); assert.equal(a.fps_num * po.fps_den, po.fps_num * a.fps_den, 'same frame rate');
    assert.equal(a.height, 720); assert.ok(copy.data.length < video.length, 'lighter than the original');
    assert.deepEqual(orig.log.filter(e => !['GET', 'HEAD'].includes(e.method)), [], 'originals only read');
    assert.deepEqual(prev.log.filter(e => !['GET', 'HEAD', 'PUT'].includes(e.method)), [], 'preview bucket: no delete');
    // second run: the copy exists -> nothing is overwritten
    const puts = prev.log.filter(e => e.method === 'PUT').length;
    const r2 = await run();
    assert.equal(r2.code, 0, r2.out); assert.match(r2.out, /exists/); assert.equal(prev.log.filter(e => e.method === 'PUT').length, puts, 'no overwrite');
    // refusals with their reasons
    const same = await run({ STUDIO_PREVIEW_R2_BUCKET: 'sportreel' });
    assert.equal(same.code, 1); assert.match(same.out, /refusing to write previews into the originals' bucket/);
    const nokey = await run({ STUDIO_PREVIEW_R2_WRITE_ACCESS_KEY_ID: '' }, ['--force']);
    assert.equal(nokey.code, 1); assert.match(nokey.out, /WRITE_ACCESS_KEY_ID/);
  } finally { orig.close(); prev.close(); }
});

test('hosted playback uses the preview when it exists, the original otherwise (both via short-lived links)', async () => {
  const orig = await startS3Stub({ bucket: 'sportreel' }), prev = await startS3Stub({ bucket: 'sportreel-previews' });
  try {
    orig.objects.set('processed/A.MP4', { data: Buffer.from('original-bytes') });
    orig.objects.set('processed/B.MP4', { data: Buffer.from('original-b') });
    prev.objects.set('processed/A.preview.mp4', { data: Buffer.from('preview-bytes') });
    const cloud = new CloudBucket({ endpoint: orig.url, bucket: 'sportreel', accessKeyId: orig.accessKeyId, secretAccessKey: orig.secretAccessKey, retries: 0 });
    const pb = new CloudBucket({ endpoint: prev.url, bucket: 'sportreel-previews', accessKeyId: prev.accessKeyId, secretAccessKey: prev.secretAccessKey, retries: 0 });
    const ctx = newCtx({ cloud }); ctx.serverless = true; ctx.allowedHosts = ['studio.example.com']; ctx.previews = { bucket: pb, find: previewLookup(pb) };
    for (const [id, key, sha] of [['sa', 'processed/A.MP4', 'a'.repeat(64)], ['sb', 'processed/B.MP4', 'b'.repeat(64)]]) ctx.db.prepare("insert into sources(id,sha256,byte_size,display_name,frame_count,fps_num,fps_den,ingest_state,created_at,provider,cloud_key) values(?,?,10,?,100,30,1,'ready',?,'cloud-r2',?)").run(id, sha, key, new Date().toISOString(), key);
    const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
    const get = p => new Promise((res, rej) => { const r = http.request({ host: '127.0.0.1', port: server.address().port, path: p, headers: { host: 'studio.example.com', authorization: 'Bearer test-token', 'x-forwarded-proto': 'https' } }, x => { let d = ''; x.on('data', c => { d += c; }); x.on('end', () => res({ status: x.statusCode, headers: x.headers, body: d })); }); r.on('error', rej); r.end(); });
    try {
      const card = JSON.parse((await get('/api/sources/sa')).body);
      assert.equal(card.playback_url, '/media/sa/proxy');
      const a = await get('/media/sa/proxy');
      assert.equal(a.status, 302); assert.equal(a.headers['x-studio-media'], 'preview');
      assert.equal(await (await fetch(a.headers.location)).text(), 'preview-bytes', 'the preview bucket serves the light copy');
      const b = await get('/media/sb/proxy');
      assert.equal(b.headers['x-studio-media'], 'original', 'no preview yet -> the original');
      assert.equal(await (await fetch(b.headers.location)).text(), 'original-b');
      assert.equal((await get('/media/sa/original')).headers['x-studio-media'], 'original', 'the original is still reachable');
      assert.deepEqual([...orig.log, ...prev.log].filter(e => !['GET', 'HEAD'].includes(e.method)), [], 'the Studio only reads');
    } finally { server.closeAllConnections(); server.close(); }
  } finally { orig.close(); prev.close(); }
});

import { spawn } from 'node:child_process';
function require_spawn(env, extra, args) {
  return spawn(process.execPath, [path.join(here, '..', 'scripts', 'make-previews.mjs'), ...args], { env: { ...env, ...extra } });
}
