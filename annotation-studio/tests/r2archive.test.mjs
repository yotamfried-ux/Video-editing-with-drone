// Protected archive adapter: SigV4 correctness, integrity, interruption recovery, no-delete guarantee, credential hygiene.
import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes, createHash } from 'node:crypto';
import { writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { signRequest } from '../server/sigv4.mjs';
import { R2Archive, ArchiveError, mirrorArchive, r2ConfigFromEnv } from '../server/r2archive.mjs';
import { LocalArchive } from '../server/archive.mjs';
import { startS3Stub } from './s3stub.mjs';
import { tmp, makeVideo, newCtx } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import { createApp } from '../server/app.mjs';

const sha = b => createHash('sha256').update(b).digest('hex');
function file(bytes) { const p = path.join(tmp('blob-'), 'f.bin'); writeFileSync(p, bytes); return p; }
async function rig(over = {}) {
  const stub = await startS3Stub();
  const archive = new R2Archive({ endpoint: stub.url, bucket: stub.bucket, accessKeyId: stub.accessKeyId, secretAccessKey: stub.secretAccessKey, retries: 1, ...over });
  return { stub, archive, done: () => stub.close() };
}

test('SigV4 signer reproduces the published AWS example signature', () => {
  // https://docs.aws.amazon.com/general/latest/gr/sigv4-calculate-signature.html (IAM ListUsers example)
  const s = signRequest({ method: 'GET', url: 'https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08', service: 'iam', region: 'us-east-1',
    headers: { 'content-type': 'application/x-www-form-urlencoded; charset=utf-8' }, payloadHash: undefined,
    accessKeyId: 'AKIDEXAMPLE', secretAccessKey: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY', amzDate: '20150830T123600Z' });
  assert.match(s.authorization, /Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7$/);
});

test('put archives, verifies by re-reading, and is idempotent', async () => {
  const { stub, archive, done } = await rig();
  try {
    const data = randomBytes(300_000), p = file(data), h = sha(data);
    const key = await archive.put(p, h, data.length);
    assert.equal(key, `sources/${h.slice(0, 2)}/${h}`); assert.deepEqual(stub.objects.get(key).data, data);
    assert.deepEqual(await archive.verify(key, h, data.length), { ok: true });
    const puts = stub.log.filter(l => l.method === 'PUT').length;
    assert.equal(await archive.put(p, h, data.length), key);
    assert.equal(stub.log.filter(l => l.method === 'PUT').length, puts, 'second put uploads nothing');
  } finally { done(); }
});

test('multipart upload for large files; interrupted multipart is aborted and a retry succeeds', async () => {
  const { stub, archive, done } = await rig({ multipartThreshold: 1000, partSize: 100_000 });
  try {
    const data = randomBytes(350_000), p = file(data), h = sha(data);
    stub.faults.failPuts = 5;                                           // outlasts the retries -> upload fails midway
    await assert.rejects(archive.put(p, h, data.length), e => e instanceof ArchiveError);
    assert.equal(stub.objects.size, 0, 'nothing published after a failed upload');
    assert.equal(stub.uploads.size, 0, 'the incomplete multipart upload was aborted');
    stub.faults.failPuts = 0;
    const key = await archive.put(p, h, data.length);
    assert.ok(stub.log.filter(l => /partNumber/.test(l.query)).length >= 4, 'uploaded in parts');
    assert.deepEqual((await archive.verify(key, h, data.length)), { ok: true });
  } finally { done(); }
});

test('corruption in transit is rejected by the server checksum and never published', async () => {
  const { stub, archive, done } = await rig();
  try {
    const data = randomBytes(10_000), p = file(data), h = sha(data);
    stub.faults.corruptNextPut = true;
    await assert.rejects(archive.put(p, h, data.length), /checksum|ARCHIVE_REJECTED|rejected|400/i);
    assert.equal(stub.objects.size, 0);
  } finally { done(); }
});

test('verify detects corruption at rest, truncation, and missing objects', async () => {
  const { stub, archive, done } = await rig();
  try {
    const data = randomBytes(5000), h = sha(data), key = await archive.put(file(data), h, data.length);
    stub.objects.get(key).data[10] ^= 1;
    assert.deepEqual(await archive.verify(key, h, data.length), { ok: false, reason: 'hash_mismatch' });
    stub.objects.get(key).data = stub.objects.get(key).data.subarray(0, 100);
    assert.deepEqual(await archive.verify(key, h, data.length), { ok: false, reason: 'size_mismatch' });
    assert.deepEqual(await archive.verify('sources/zz/none', h, 1), { ok: false, reason: 'missing' });
  } finally { done(); }
});

test('the adapter can never delete or replace archived objects', async () => {
  const { stub, archive, done } = await rig({ multipartThreshold: 1000, partSize: 100_000 });
  try {
    assert.equal(typeof archive.delete, 'undefined'); assert.equal(typeof archive.remove, 'undefined'); assert.equal(typeof archive.overwrite, 'undefined');
    const data = randomBytes(250_000), h = sha(data);
    await archive.put(file(data), h, data.length);
    await archive.put(file(data), h, data.length);
    await archive.abortIncompleteUploads();
    assert.equal(stub.log.filter(l => l.objectDelete).length, 0, 'no object DELETE was ever issued');
  } finally { done(); }
});

test('credentials never leak into errors, logs, or serialization', async () => {
  const { stub, archive, done } = await rig();
  try {
    const bad = new R2Archive({ endpoint: stub.url, bucket: stub.bucket, accessKeyId: stub.accessKeyId, secretAccessKey: 'WRONG-SECRET-VALUE', retries: 0 });
    const err = await bad.verify('sources/aa/x', 'a'.repeat(64), 1).catch(e => e);
    for (const blob of [String(err), err.stack ?? '', JSON.stringify(bad), JSON.stringify(archive), JSON.stringify(Object.keys(bad))]) {
      assert.ok(!blob.includes('WRONG-SECRET-VALUE') && !blob.includes(stub.secretAccessKey) && !blob.includes(stub.accessKeyId), 'no credential material');
    }
    assert.equal(err.code, 'ARCHIVE_REJECTED');
    assert.throws(() => r2ConfigFromEnv({}), /STUDIO_R2_BUCKET|STUDIO_R2_ACCOUNT_ID/);
  } finally { done(); }
});

test('storage outage is retryable and recorded; nothing half-registered', async () => {
  const { stub, archive, done } = await rig();
  try {
    stub.faults.outage = true;
    const data = randomBytes(2000);
    await assert.rejects(archive.put(file(data), sha(data), data.length), e => e.code === 'ARCHIVE_RETRYABLE');
    stub.faults.outage = false;
    assert.ok(await archive.put(file(data), sha(data), data.length));
  } finally { done(); }
});

test('list paginates; mirror copies missing objects, skips identical ones, flags corrupt sources', async () => {
  const { stub, archive, done } = await rig();
  const local = new LocalArchive(tmp('mirror-'));
  try {
    const blobs = [randomBytes(1500), randomBytes(1600), randomBytes(1700), randomBytes(1800), randomBytes(1900)];
    for (const b of blobs) await archive.put(file(b), sha(b), b.length);
    assert.equal((await archive.list()).length, 5, 'pagination across 3 pages');
    const r1 = await mirrorArchive(archive, local, { tmpDir: tmp('m-') });
    assert.deepEqual([r1.copied, r1.skipped, r1.failed.length], [5, 0, 0]);
    for (const b of blobs) assert.deepEqual(await local.verify(local.keyFor(sha(b)), sha(b), b.length), { ok: true });
    const r2 = await mirrorArchive(archive, local, { tmpDir: tmp('m-') });
    assert.deepEqual([r2.copied, r2.skipped], [0, 5], 'idempotent');
    const k = archive.keyFor(sha(blobs[0])); stub.objects.get(k).data[0] ^= 1;
    const dst2 = new LocalArchive(tmp('mirror2-'));
    const r3 = await mirrorArchive(archive, dst2, { tmpDir: tmp('m-') });
    assert.equal(r3.failed.length, 1); assert.equal(r3.failed[0].reason, 'source_hash_mismatch', 'corrupt source is never propagated');
  } finally { done(); }
});

test('Studio ingest + authenticated range playback work on the R2 backend (real video, stub storage)', async () => {
  const { stub, archive, done } = await rig();
  try {
    const raw = path.join(tmp('ops-'), 'raw');
    makeVideo(path.join(raw, 'a.mp4'), { seconds: 2, tag: 'r2' });
    const ctx = newCtx({ archive });
    await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
    const s = ctx.db.prepare('select * from sources').get();
    assert.equal(s.ingest_state, 'ready'); assert.ok(s.archive_key.startsWith('sources/'));
    assert.equal(stub.objects.size, 1);
    const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
    const base = `http://127.0.0.1:${server.address().port}`, h = { authorization: 'Bearer test-token' };
    const r = await fetch(`${base}/media/${s.id}/original`, { headers: { ...h, range: 'bytes=0-99' } });
    assert.equal(r.status, 206); assert.equal((await r.arrayBuffer()).byteLength, 100);
    assert.equal((await fetch(`${base}/media/${s.id}/original`)).status, 401, 'no public access path to the archive');
    const body = JSON.stringify(await (await fetch(`${base}/api/sources/${s.id}`, { headers: h })).json());
    assert.ok(!body.includes(stub.secretAccessKey) && !body.includes(stub.accessKeyId) && !body.includes(stub.url), 'API never exposes storage credentials or endpoint');
    // production reset: operational files vanish, archive playback still works
    const again = await fetch(`${base}/media/${s.id}/original`, { headers: { ...h, range: 'bytes=0-9' } });
    assert.equal(again.status, 206);
    server.closeAllConnections(); server.close();
  } finally { done(); }
});
void mkdirSync;
