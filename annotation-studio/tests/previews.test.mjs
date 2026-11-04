// Light playback copies in the EXISTING bucket under studio/previews/ (operator decision). The uploader writes only with
// an R2 temporary credential limited to PutObject under studio/previews/ (enforced by the storage, emulated here as R2
// checks it: HS256 JWT by the parent secret, signature with sha256(jwt), bucket/actions/prefix limits), create-once
// (If-None-Match: *). Originals can be read by the Studio, never written, replaced or deleted. Each refusal asserts
// its specific reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { newCtx, tmp } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';
import { CloudBucket } from '../server/cloud.mjs';
import { createApp } from '../server/app.mjs';
import { previewKey, previewLookup, probeFile, putPreview, previewWriteCredentials, r2TempCredentials, PREVIEW_PREFIX } from '../server/previews.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const PARENT = { accessKeyId: 'AKIAPARENTRW', secretAccessKey: 'parent-secret-do-not-use' };
function original(file) {   // 59.94 fps constant frame rate, like the DJI originals (1080p, 2 s, for speed)
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=60000/1001:d=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', file]);
  assert.equal(r.status, 0, String(r.stderr)); return file;
}
const tempCreds = (stub, extra = {}) => previewWriteCredentials({ endpoint: stub.url, accountId: 'acct', parentAccessKeyId: PARENT.accessKeyId, parentSecretAccessKey: PARENT.secretAccessKey, bucket: 'sportreel', ...extra });

test('preview keys live under studio/previews/, next to nothing the pipeline owns', () => {
  assert.equal(previewKey('processed/2026-10-04T07-38-33_DJI_20260724103751_0165_D.MP4'), 'studio/previews/processed/2026-10-04T07-38-33_DJI_20260724103751_0165_D.mp4');
  assert.ok(previewKey('raw/a.b/c.mov').startsWith(PREVIEW_PREFIX));
});

test('storage-enforced isolation: the temporary credential can only PUT under studio/previews/ - not overwrite, read or delete originals', async () => {
  const s3 = await startS3Stub({ bucket: 'sportreel', ...PARENT });
  try {
    s3.objects.set('processed/DJI_0001.MP4', { data: Buffer.from('ORIGINAL-4K') });
    const c = tempCreds(s3), f = path.join(tmp('pv-'), 'x.mp4'); writeFileSync(f, 'preview');
    // allowed: a new object under the prefix
    assert.deepEqual(await putPreview({ endpoint: s3.url, bucket: 'sportreel', creds: c, key: 'studio/previews/processed/DJI_0001.mp4', file: f }), { created: true });
    // create-once: R2 refuses to replace it (412), the uploader reports "not created" and nothing changes
    writeFileSync(f, 'other');
    assert.deepEqual(await putPreview({ endpoint: s3.url, bucket: 'sportreel', creds: c, key: 'studio/previews/processed/DJI_0001.mp4', file: f }), { created: false });
    assert.equal(s3.objects.get('studio/previews/processed/DJI_0001.mp4').data.toString(), 'preview');
    // the uploader refuses keys outside the prefix before sending anything
    await assert.rejects(putPreview({ endpoint: s3.url, bucket: 'sportreel', creds: c, key: 'processed/DJI_0001.MP4', file: f }), /refusing to write outside studio\/previews\//);
    // and even a request crafted around the uploader is refused BY THE STORAGE with this credential
    const raw = async (method, key, body) => {
      const { signRequest, sha256hex } = await import('../server/sigv4.mjs');
      const url = `${s3.url}/sportreel/${key}`;
      const { _canonical, ...h } = signRequest({ method, url, headers: { 'x-amz-security-token': c.sessionToken }, payloadHash: sha256hex(body ?? ''), region: 'auto', service: 's3', accessKeyId: c.accessKeyId, secretAccessKey: c.secretAccessKey });
      return (await fetch(url, { method, headers: h, body })).status;
    };
    assert.equal(await raw('PUT', 'processed/DJI_0001.MP4', 'overwrite'), 403, 'overwrite of an original refused by R2');
    assert.equal(await raw('DELETE', 'processed/DJI_0001.MP4'), 403, 'delete of an original refused by R2');
    assert.equal(await raw('DELETE', 'studio/previews/processed/DJI_0001.mp4'), 403, 'delete of a preview refused too (PutObject only)');
    assert.equal(await raw('GET', 'processed/DJI_0001.MP4'), 403, 'not even reads');
    assert.equal(s3.objects.get('processed/DJI_0001.MP4').data.toString(), 'ORIGINAL-4K', 'the original is untouched');
    // an expired credential or one signed with another secret is refused
    const old = tempCreds(s3, { ttlSeconds: 60, now: Date.now() - 3600 * 1000 });
    await assert.rejects(putPreview({ endpoint: s3.url, bucket: 'sportreel', creds: old, key: 'studio/previews/y.mp4', file: f }), /returned 403/);
    const forged = r2TempCredentials({ endpoint: s3.url, accountId: 'acct', parentAccessKeyId: PARENT.accessKeyId, parentSecretAccessKey: 'guessed', bucket: 'sportreel', actions: ['PutObject', 'DeleteObject'], prefixPaths: [''] });
    await assert.rejects(putPreview({ endpoint: s3.url, bucket: 'sportreel', creds: forged, key: 'studio/previews/z.mp4', file: f }), /returned 403/);
  } finally { s3.close(); }
});

test('make-previews: 720p, frame for frame, into studio/previews/ of the same bucket; reruns skip; originals only read', async () => {
  const RO = { id: 'AKIASTUDIORO', secret: 'studio-read-only-secret' };
  const s3 = await startS3Stub({ bucket: 'sportreel', ...PARENT, readOnlyKeys: { [RO.id]: RO.secret } });
  try {
    const video = readFileSync(original(path.join(tmp('pv-'), 'DJI_0001.MP4')));
    s3.objects.set('processed/DJI_0001.MP4', { data: video });
    const env = { ...process.env, STUDIO_CLOUD_R2_ENDPOINT: s3.url, STUDIO_CLOUD_R2_ACCOUNT_ID: 'acct', STUDIO_CLOUD_R2_BUCKET: 'sportreel', STUDIO_CLOUD_R2_ACCESS_KEY_ID: RO.id, STUDIO_CLOUD_R2_SECRET_ACCESS_KEY: RO.secret,
      STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID: PARENT.accessKeyId, STUDIO_PREVIEW_PARENT_SECRET_ACCESS_KEY: PARENT.secretAccessKey, STUDIO_CLOUD_INCLUDE: 'DJI' };
    const run = (extra = {}, args = []) => new Promise(res => { const p = spawn(process.execPath, [path.join(here, '..', 'scripts', 'make-previews.mjs'), ...args], { env: { ...env, ...extra } }); let out = ''; p.stdout.on('data', d => { out += d; }); p.stderr.on('data', d => { out += d; }); p.on('close', code => res({ code, out })); });
    const dry = await run({}, ['--dry-run']);
    assert.equal(dry.code, 0, dry.out); assert.match(dry.out, /dry run, nothing written/);
    assert.equal(s3.log.filter(e => e.method === 'PUT').length, 0, 'dry run wrote nothing');
    const r1 = await run();
    assert.equal(r1.code, 0, r1.out); assert.match(r1.out, /OK studio\/previews\/processed\/DJI_0001\.mp4/); assert.match(r1.out, /original unchanged \(etag [0-9a-f]+\)/);
    const copy = s3.objects.get('studio/previews/processed/DJI_0001.mp4');
    assert.ok(copy, 'stored under studio/previews/ in the same bucket');
    const puts = s3.log.filter(e => e.method === 'PUT');
    assert.equal(puts.length, 1); assert.deepEqual(puts[0].temp.actions, ['PutObject']); assert.deepEqual(puts[0].temp.paths.prefixPaths, ['studio/previews/']);
    const f = path.join(tmp('pv-'), 'copy.mp4'); writeFileSync(f, copy.data);
    const src = path.join(tmp('pv-'), 'o.mp4'); writeFileSync(src, video);
    const a = await probeFile(f), o = await probeFile(src);
    assert.equal(a.frame_count, o.frame_count, 'same number of frames'); assert.equal(a.fps_num * o.fps_den, o.fps_num * a.fps_den, 'same frame rate');
    assert.equal(a.height, 720); assert.ok(copy.data.length < video.length, 'lighter than the original');
    assert.ok(s3.objects.get('processed/DJI_0001.MP4').data.equals(video), 'original byte-identical');
    assert.deepEqual(s3.log.filter(e => !['GET', 'HEAD', 'PUT'].includes(e.method)), [], 'nothing deleted');
    // rerun: the copy exists -> skipped, no write at all
    const r2 = await run();
    assert.equal(r2.code, 0, r2.out); assert.match(r2.out, /exists/); assert.equal(s3.log.filter(e => e.method === 'PUT').length, 1);
    // refusals with their reasons
    const same = await run({ STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID: RO.id });
    assert.equal(same.code, 1); assert.match(same.out, /parent key must not be the Studio read-only key/);
    const nokey = await run({ STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID: '' });
    assert.equal(nokey.code, 1); assert.match(nokey.out, /STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID/);
  } finally { s3.close(); }
});

test('hosted playback uses studio/previews/ when the copy exists, the original otherwise (short-lived read links)', async () => {
  const s3 = await startS3Stub({ bucket: 'sportreel' });
  try {
    s3.objects.set('processed/A.MP4', { data: Buffer.from('original-a') });
    s3.objects.set('processed/B.MP4', { data: Buffer.from('original-b') });
    s3.objects.set('studio/previews/processed/A.mp4', { data: Buffer.from('preview-a') });
    const cloud = new CloudBucket({ endpoint: s3.url, bucket: 'sportreel', accessKeyId: s3.accessKeyId, secretAccessKey: s3.secretAccessKey, retries: 0 });
    const ctx = newCtx({ cloud }); ctx.serverless = true; ctx.allowedHosts = ['studio.example.com']; ctx.previews = { bucket: cloud, find: previewLookup(cloud) };
    for (const [id, key, sha] of [['sa', 'processed/A.MP4', 'a'.repeat(64)], ['sb', 'processed/B.MP4', 'b'.repeat(64)]]) ctx.db.prepare("insert into sources(id,sha256,byte_size,display_name,frame_count,fps_num,fps_den,ingest_state,created_at,provider,cloud_key) values(?,?,10,?,100,30,1,'ready',?,'cloud-r2',?)").run(id, sha, key, new Date().toISOString(), key);
    const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
    const get = p => new Promise((res, rej) => { const r = http.request({ host: '127.0.0.1', port: server.address().port, path: p, headers: { host: 'studio.example.com', authorization: 'Bearer test-token', 'x-forwarded-proto': 'https' } }, x => { let d = ''; x.on('data', c => { d += c; }); x.on('end', () => res({ status: x.statusCode, headers: x.headers, body: d })); }); r.on('error', rej); r.end(); });
    try {
      assert.equal(JSON.parse((await get('/api/sources/sa')).body).playback_url, '/media/sa/proxy');
      const a = await get('/media/sa/proxy');
      assert.equal(a.status, 302); assert.equal(a.headers['x-studio-media'], 'preview');
      assert.equal(await (await fetch(a.headers.location)).text(), 'preview-a');
      const b = await get('/media/sb/proxy');
      assert.equal(b.headers['x-studio-media'], 'original', 'no copy yet -> the original');
      assert.equal(await (await fetch(b.headers.location)).text(), 'original-b');
      assert.deepEqual(s3.log.filter(e => !['GET', 'HEAD'].includes(e.method)), [], 'the Studio only reads');
    } finally { server.closeAllConnections(); server.close(); }
  } finally { s3.close(); }
});
