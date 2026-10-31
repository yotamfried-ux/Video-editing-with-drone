// Cloud catalog: SportReel's existing videos in R2 used IN PLACE. Real ffmpeg media served by an in-memory S3 stub.
// Proves: read-only access, catalog + availability + pipeline state, ranged streaming/seeking, annotation, persistence,
// verification gate before Ground Truth approval, and that the bucket is never modified.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';
import { CloudBucket, waitForProxies, parseCsv, loadMetadata, unXml } from '../server/cloud.mjs';
import { createApp } from '../server/app.mjs';
import { createContext } from '../server/context.mjs';
import * as A from '../server/annotations.mjs';

const sha = b => createHash('sha256').update(b).digest('hex');
const md5 = b => createHash('md5').update(b).digest('hex');

async function world({ record = true } = {}) {
  const stub = await startS3Stub({ bucket: 'sportreel' });
  const dir = tmp('cloudvid-');
  const vid = n => readFileSync(makeVideo(path.join(dir, `${n}.mp4`), { seconds: 3, y: 20 + n.charCodeAt(0), tag: n }));
  const files = { A: vid('A'), B: vid('B'), L: vid('L') };
  stub.objects.set('raw/2026-10-06T17-37-55_A.mp4', { data: files.A });
  stub.objects.set('raw/2026-10-06T17-46-01_B.mp4', { data: files.B });
  stub.objects.set('processed/2026-09-01T08-00-00_L.mp4', { data: files.L });          // legacy: only under processed/
  stub.objects.set('review/draft_of_A.mp4', { data: Buffer.from('a derived draft, never a source') });
  stub.objects.set('metadata/keep.json', { data: Buffer.from('{}') });
  // the pipeline's processed marker for A (size + ETag pinned)
  stub.objects.set(`metadata/source_state/${sha('raw/2026-10-06T17-37-55_A.mp4')}.json`, { data: Buffer.from(JSON.stringify({ source_key: 'raw/2026-10-06T17-37-55_A.mp4', size: files.A.length, etag: `"${md5(files.A)}"` })) });
  const home = tmp('studio-cloud-');
  const metaFile = path.join(home, 'meta.json');
  const rows = [
    { id: 'u-A', status: 'verified', storage_key: 'raw/2026-10-06T17-37-55_A.mp4', verified_size_bytes: files.A.length, content_sha256: sha(files.A), created_at: '2026-10-06T17:37:55Z', batch_id: 'batch1' },
    { id: 'u-B', status: 'verified', storage_key: 'raw/2026-10-06T17-46-01_B.mp4', verified_size_bytes: files.B.length, content_sha256: record ? sha(files.B) : null, created_at: '2026-10-06T17:46:01Z', batch_id: 'batch1' },
    { id: 'u-L', status: 'verified', storage_key: 'raw/2026-09-01T08-00-00_L.mp4', verified_size_bytes: files.L.length, content_sha256: sha(files.L), created_at: '2026-09-01T08:00:00Z', batch_id: 'batch0' },
    { id: 'u-G', status: 'verified', storage_key: 'raw/2026-10-10T10-00-00_GONE.mp4', verified_size_bytes: 123, content_sha256: 'f'.repeat(64), created_at: '2026-10-10T10:00:00Z', batch_id: 'batch2' },
    { id: 'u-X', status: 'aborted', storage_key: 'raw/aborted.mp4', removed_at: '2026-10-03T00:00:00Z' },
  ];
  mkdirSyncCompat(home); writeFileSync(metaFile, JSON.stringify(rows));
  const cloud = new CloudBucket({ endpoint: stub.url, bucket: 'sportreel', accessKeyId: stub.accessKeyId, secretAccessKey: stub.secretAccessKey, retries: 0 });
  const ctx = createContext(home, { token: 'cloud-token', cloud });
  ctx.cloudMetadata = metaFile;
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const api = async (p, o = {}) => { const r = await fetch(base + p, { method: o.method ?? 'GET', headers: { authorization: 'Bearer cloud-token', 'content-type': 'application/json', ...(o.headers ?? {}) }, body: o.body ? JSON.stringify(o.body) : undefined }); const t = await r.text(); return { status: r.status, body: t && r.headers.get('content-type')?.includes('json') ? JSON.parse(t) : t, headers: r.headers, raw: t }; };
  const job = async (p, o) => { const r = await api(p, { method: 'POST', ...o }); assert.equal(r.status, 202, JSON.stringify(r.body)); for (let i = 0; i < 400; i++) { const j = (await api(`/api/jobs/${r.body.job_id}`)).body; if (j.state !== 'running') return j; await new Promise(x => setTimeout(x, 100)); } throw new Error('job timeout'); };
  const snapshot = () => new Map([...stub.objects].map(([k, v]) => [k, md5(v.data)]));
  return { stub, ctx, server, base, api, job, files, home, snapshot, cloud, close: () => { server.closeAllConnections(); server.close(); stub.close(); } };
}
import { mkdirSync } from 'node:fs';
const mkdirSyncCompat = d => mkdirSync(d, { recursive: true });

test('the cloud client is read-only by construction and holds its credentials privately', async () => {
  const w = await world();
  try {
    const methods = Object.getOwnPropertyNames(CloudBucket.prototype);
    assert.deepEqual(methods.filter(m => /put|delete|remove|copy|write|upload|abort|create/i.test(m)), [], `no write-capable method: ${methods}`);
    assert.ok(!JSON.stringify(w.cloud).includes(w.stub.secretAccessKey) && !JSON.stringify(w.cloud).includes(w.stub.accessKeyId), 'serialising the client leaks nothing');
    assert.ok(!Object.values(w.cloud).some(v => v === w.stub.secretAccessKey), 'no secret on an enumerable property');
  } finally { w.close(); }
});

test('catalog: lists the source prefixes only, with availability, pipeline state, identity and flags a record without an object as missing', async () => {
  const w = await world();
  try {
    const before = w.snapshot();
    const j = await w.job('/api/cloud/sync');
    assert.equal(j.state, 'done', JSON.stringify(j));
    assert.deepEqual({ raw: j.report.raw, legacy: j.report.processed_legacy, missing: j.report.missing }, { raw: 2, legacy: 1, missing: 1 });
    const { items } = (await w.api('/api/cloud/objects')).body;
    const by = Object.fromEntries(items.map(i => [i.name ?? i.key, i]));
    assert.equal(items.length, 4, 'A, B, legacy L, and the missing record G (review/ outputs are never catalogued)');
    assert.ok(!items.some(i => i.key.startsWith('review/') || i.key.startsWith('metadata/')));
    const A_ = items.find(i => i.key.endsWith('_A.mp4')), B_ = items.find(i => i.key.endsWith('_B.mp4')), L_ = items.find(i => i.key.startsWith('processed/')), G_ = items.find(i => i.key.includes('GONE'));
    assert.equal(A_.pipeline_state, 'processed', 'the pipeline marker matches size+ETag'); assert.equal(B_.pipeline_state, 'new');
    assert.equal(L_.availability, 'legacy_processed'); assert.equal(G_.availability, 'missing');
    assert.equal(A_.availability, 'available'); assert.equal(A_.identity, 'recorded'); assert.equal(A_.uploaded_at, '2026-10-06T17:37:55Z');
    assert.equal(A_.annotation_status, 'not_annotated');
    assert.ok(!items.some(i => i.key.includes('aborted')), 'aborted records are not sources');
    assert.deepEqual(w.snapshot(), before, 'listing changed nothing in the bucket');
    assert.ok(w.stub.log.every(l => l.method === 'GET' || l.method === 'HEAD'), 'only GET/HEAD were ever issued');
    const st = (await w.api('/api/cloud/status')).body;
    assert.deepEqual({ configured: st.configured, read_only: st.read_only, total: st.total }, { configured: true, read_only: true, total: 4 });
    assert.ok(!JSON.stringify(st).includes(w.stub.secretAccessKey));
  } finally { w.close(); }
});

test('open → view with Range seeking → annotate → persists; Ground Truth needs verification; the bucket never changes', async () => {
  const w = await world();
  try {
    const before = w.snapshot();
    await w.job('/api/cloud/sync');
    const B_ = (await w.api('/api/cloud/objects')).body.items.find(i => i.key.endsWith('_B.mp4'));
    const opened = await w.job(`/api/cloud/objects/${B_.id}/open`);
    assert.equal(opened.state, 'done', JSON.stringify(opened));
    const sid = opened.report.source_id;
    const src = (await w.api(`/api/sources/${sid}`)).body;
    assert.equal(src.provider, 'cloud-r2'); assert.equal(src.verify_state, 'unverified');
    assert.equal(src.sha256, sha(w.files.B), 'identity comes from the durable record');
    assert.ok(src.frame_count >= 85 && src.width === 320, JSON.stringify(src));
    assert.equal(w.ctx.db.prepare('select codec from sources where id=?').get(sid).codec, 'h264');
    assert.ok(src.thumb_url, 'thumbnail built straight from the cloud object');

    // viewing: ranged reads (seeking) return exactly the requested bytes of the original, through the authenticated route
    const full = (await w.api(`/media/${sid}/original`));
    assert.equal(full.status, 200); assert.equal(Number(full.headers.get('content-length')), w.files.B.length);
    const mid = await fetch(`${w.base}/media/${sid}/original`, { headers: { authorization: 'Bearer cloud-token', range: 'bytes=1000-1999' } });
    assert.equal(mid.status, 206); assert.equal(mid.headers.get('content-range'), `bytes 1000-1999/${w.files.B.length}`);
    assert.ok(Buffer.from(await mid.arrayBuffer()).equals(w.files.B.subarray(1000, 2000)), 'the exact byte range of the original');
    const tail = await fetch(`${w.base}/media/${sid}/original`, { headers: { authorization: 'Bearer cloud-token', range: `bytes=${w.files.B.length - 500}-` } });
    assert.equal(tail.status, 206); assert.equal((await tail.arrayBuffer()).byteLength, 500);
    assert.equal((await fetch(`${w.base}/media/${sid}/original`)).status, 401, 'no token, no video');
    assert.ok(!full.raw.includes('AKIATESTKEY'));

    // frame-exact proxy is generated locally from the cloud object; it never goes back to the bucket
    await waitForProxies();
    const withProxy = (await w.api(`/api/sources/${sid}`)).body;
    assert.equal(withProxy.proxy_state, 'ready'); assert.match(withProxy.playback_url, /\/proxy$/);
    assert.equal((await w.api(`/media/${sid}/proxy`)).status, 200);

    // annotate + save + reload from a brand-new process
    const ath = A.createAthlete(w.ctx.db, 'דנה');
    const c = A.emptyContent(); c.segments.push(seg('s1', 5, 40, { athlete_id: ath.id })); c.reviewed_ranges.push({ start_frame: 0, end_frame: src.frame_count });
    const put = await w.api(`/api/sources/${sid}/draft`, { method: 'PUT', body: { expected_version: 0, content: c } });
    assert.equal(put.status, 200, JSON.stringify(put.body));
    const refused = await w.api(`/api/sources/${sid}/approve`, { method: 'POST', body: { expected_version: 1 } });
    assert.equal(refused.status, 409); assert.equal(refused.body.code, 'SOURCE_UNVERIFIED', 'Ground Truth is not approved on an unverified cloud source');
    const ver = await w.job('/api/cloud/verify', { body: {} });
    assert.deepEqual({ checked: ver.report.checked, verified: ver.report.verified, mismatched: ver.report.mismatched.length }, { checked: 1, verified: 1, mismatched: 0 });
    const ok = await w.api(`/api/sources/${sid}/approve`, { method: 'POST', body: { expected_version: 1, acknowledge_unresolved: true } });
    assert.equal(ok.status, 200, JSON.stringify(ok.body));

    const home = w.home; w.ctx.db.close();
    const again = createContext(home, { token: 'cloud-token', cloud: w.cloud });
    assert.equal(A.getDraft(again.db, sid).content.segments.length, 1, 'annotation survives closing and reopening');
    assert.equal(A.listRevisions(again.db, sid).length, 1);
    assert.equal(again.db.prepare('select count(*) n from cloud_objects').get().n, 4);
    again.db.close();

    assert.deepEqual(w.snapshot(), before, 'the original and every other object in the bucket are byte-identical afterwards');
    assert.ok(w.stub.log.every(l => l.method === 'GET' || l.method === 'HEAD'), `never anything but GET/HEAD: ${[...new Set(w.stub.log.map(l => l.method))]}`);
    assert.ok(w.stub.log.every(l => !l.objectDelete));
  } finally { w.close(); }
});

test('an object whose bytes differ from the durable record is flagged mismatch and cannot become Ground Truth', async () => {
  const w = await world();
  try {
    await w.job('/api/cloud/sync');
    const B_ = (await w.api('/api/cloud/objects')).body.items.find(i => i.key.endsWith('_B.mp4'));
    const sid = (await w.job(`/api/cloud/objects/${B_.id}/open`)).report.source_id;
    await waitForProxies();
    const k = 'raw/2026-10-06T17-46-01_B.mp4';
    const flipped = Buffer.from(w.stub.objects.get(k).data); flipped[flipped.length - 10] ^= 0xff;
    w.stub.objects.set(k, { data: flipped });
    const ver = await w.job('/api/cloud/verify', { body: {} });
    assert.equal(ver.report.mismatched.length, 1);
    assert.equal(w.ctx.db.prepare('select verify_state v from sources where id=?').get(sid).v, 'mismatch');
    const c = A.emptyContent(); c.segments.push(seg('s1', 5, 40));
    await w.api(`/api/sources/${sid}/draft`, { method: 'PUT', body: { expected_version: 0, content: c } });
    assert.equal((await w.api(`/api/sources/${sid}/approve`, { method: 'POST', body: { expected_version: 1, acknowledge_unresolved: true } })).body.code, 'SOURCE_UNVERIFIED');
  } finally { w.close(); }
});

test('without a durable record the identity is computed from the bytes; the same bytes already catalogued locally are linked, not duplicated', async () => {
  const w = await world({ record: false });
  try {
    await w.job('/api/cloud/sync');
    const B_ = (await w.api('/api/cloud/objects')).body.items.find(i => i.key.endsWith('_B.mp4'));
    assert.equal(B_.identity, 'unknown');
    const sid = (await w.job(`/api/cloud/objects/${B_.id}/open`)).report.source_id;
    const row = w.ctx.db.prepare('select sha256, verify_state from sources where id=?').get(sid);
    assert.equal(row.sha256, sha(w.files.B)); assert.equal(row.verify_state, 'verified', 'hashed from the actual bytes');
    // the very same bytes appearing again under another key (e.g. a legacy copy) are linked to the same source
    w.stub.objects.set('raw/copy_of_B.mp4', { data: w.files.B });
    await w.job('/api/cloud/sync');
    const copy = (await w.api('/api/cloud/objects')).body.items.find(i => i.key === 'raw/copy_of_B.mp4');
    const linked = await w.job(`/api/cloud/objects/${copy.id}/open`);
    assert.equal(linked.report.source_id, sid); assert.equal(linked.report.reused, true);
    assert.equal(w.ctx.db.prepare("select count(*) n from sources where provider='cloud-r2'").get().n, 1);
  } finally { w.close(); }
});

test('opening the same object twice at once registers it once', async () => {
  const w = await world();
  try {
    await w.job('/api/cloud/sync');
    const B_ = (await w.api('/api/cloud/objects')).body.items.find(i => i.key.endsWith('_B.mp4'));
    const [a, b] = await Promise.all([w.job(`/api/cloud/objects/${B_.id}/open`), w.job(`/api/cloud/objects/${B_.id}/open`)]);
    assert.equal(a.state, 'done'); assert.equal(b.state, 'done');
    assert.equal(a.report.source_id, b.report.source_id);
    assert.equal(w.ctx.db.prepare("select count(*) n from sources where provider='cloud-r2'").get().n, 1);
    await waitForProxies();
  } finally { w.close(); }
});

test('not configured: clear message, no crash, nothing exposed', async () => {
  const ctx = newCtx(); ctx.cloud = null;
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const h = { authorization: 'Bearer test-token' };
    assert.equal((await (await fetch(`${base}/api/cloud/status`, { headers: h })).json()).configured, false);
    const r = await fetch(`${base}/api/cloud/objects`, { headers: h });
    assert.equal(r.status, 503); assert.equal((await r.json()).code, 'CLOUD_NOT_CONFIGURED');
  } finally { server.closeAllConnections(); server.close(); }
});

test('the cloud module cannot issue a write: no write verb or write API appears anywhere in its source', () => {
  const src = readFileSync(new URL('../server/cloud.mjs', import.meta.url), 'utf8');
  const verbs = [...src.matchAll(/'(PUT|POST|DELETE|PATCH)'/g)].map(m => m[1]);
  assert.deepEqual(verbs, [], 'no write verb is ever named (the only guard is the allow-list of GET/HEAD)');
  assert.ok(/method !== 'GET' && method !== 'HEAD'/.test(src), 'the request primitive rejects everything except GET/HEAD');
  assert.ok(!/x-amz-copy-source|[?&]uploadId=|\?uploads|DeleteObject|PutObject|CompleteMultipartUpload/i.test(src));
});

test('metadata can be a JSON export or a Supabase CSV export (quotes, commas, CRLF, BOM) and ignores aborted/removed records', () => {
  const csv = '\uFEFFid,status,storage_key,source_filename,source_size_bytes,verified_size_bytes,content_sha256,created_at,batch_id\r\n'
    + 'u1,verified,raw/a.mp4,"my, ""quoted"" name.mp4",100,100,' + 'a'.repeat(64) + ',2026-10-06T10:00:00Z,b1\r\n'
    + 'u2,aborted,raw/b.mp4,b.mp4,5,,,2026-10-06T10:00:00Z,b1\r\n'
    + 'u3,superseded,raw/c.mp4,c.mp4,7,7,' + 'c'.repeat(64) + ',2026-10-07T10:00:00Z,b1\r\n';
  assert.equal(parseCsv(csv.replace(/^\uFEFF/, ''))[0].source_filename, 'my, "quoted" name.mp4');
  const f = path.join(tmp('csv-'), 'uploads.csv'); writeFileSync(f, csv);
  const rows = loadMetadata(f);
  assert.deepEqual(rows.map(r => [r.key, r.status, r.size]), [['raw/a.mp4', 'verified', 100], ['raw/c.mp4', 'superseded', 7]]);
  assert.equal(rows[0].sha256, 'a'.repeat(64)); assert.equal(rows[0].name, 'my, "quoted" name.mp4');
});

test('XML entities in object keys are decoded exactly once (no double unescaping)', () => {
  assert.equal(unXml('raw/a&amp;b.mp4'), 'raw/a&b.mp4');
  assert.equal(unXml('raw/&amp;lt;tag&amp;gt;.mp4'), 'raw/&lt;tag&gt;.mp4', '&amp;lt; is the literal text &lt;, not "<"');
  assert.equal(unXml('&lt;&gt;&quot;&apos;&amp;'), '<>"\'&');
  assert.equal(unXml('&amp;amp;'), '&amp;');
});
