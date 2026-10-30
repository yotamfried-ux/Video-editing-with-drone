// M2: durable catalog — identity, dedup, archive, reconcile, move/cleanup survival, failure modes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, copyFileSync, renameSync, rmSync, existsSync, writeFileSync, appendFileSync, statSync, chmodSync, truncateSync } from 'node:fs';
import path from 'node:path';
import { newCtx, makeVideo, tmp } from './helpers.mjs';
import { ingestFile, reconcile, verifyArchives, ensureBatch, IngestError } from '../server/ingest.mjs';

async function setup() {
  const ctx = newCtx(); const ops = tmp('ops-');
  return { ctx, ops, raw: path.join(ops, 'raw'), processed: path.join(ops, 'processed') };
}
const roots = e => [{ dir: e.raw, prefix: 'raw/' }, { dir: e.processed, prefix: 'processed/' }];

test('ingest registers a source, verifies archive, creates derivatives', async () => {
  const e = await setup();
  const f = makeVideo(path.join(e.raw, 'a.mp4'), { tag: 'one' });
  const r = await ingestFile(e.ctx, { filePath: f, locationKey: 'raw/a.mp4', batchId: ensureBatch(e.ctx, 'b1') });
  assert.equal(r.archived, true); assert.equal(r.duplicate, false);
  const s = e.ctx.db.prepare('select * from sources').get();
  assert.equal(s.ingest_state, 'ready'); assert.equal(s.frame_count, 120); assert.equal(s.fps_num / s.fps_den, 30);
  assert.ok(s.archive_verified_at); assert.ok(existsSync(s.thumb_path)); assert.ok(existsSync(s.proxy_path));
  assert.equal((statSync(e.ctx.archive.pathFor(s.archive_key)).mode & 0o222), 0, 'archive file is read-only');
});

test('same bytes under different names/batches => one source, multiple occurrences', async () => {
  const e = await setup();
  const a = makeVideo(path.join(e.raw, 'a.mp4'), { tag: 'x' });
  copyFileSync(a, path.join(e.raw, 'copy-of-a.mp4'));
  const b1 = ensureBatch(e.ctx, 'b1'), b2 = ensureBatch(e.ctx, 'b2');
  const r1 = await ingestFile(e.ctx, { filePath: a, locationKey: 'raw/a.mp4', batchId: b1 });
  const r2 = await ingestFile(e.ctx, { filePath: path.join(e.raw, 'copy-of-a.mp4'), locationKey: 'raw/copy-of-a.mp4', batchId: b2 });
  assert.equal(r2.duplicate, true); assert.equal(r1.sourceId, r2.sourceId);
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 1);
  assert.equal(e.ctx.db.prepare('select count(*) n from upload_occurrences').get().n, 2);
});

test('same filename with different bytes => different sources', async () => {
  const e = await setup(); const b = ensureBatch(e.ctx, 'b');
  const p = path.join(e.raw, 'clip.mp4');
  makeVideo(p, { tag: 'v1' }); const r1 = await ingestFile(e.ctx, { filePath: p, locationKey: 'raw/clip.mp4', batchId: b });
  makeVideo(p, { tag: 'v2', y: 20 }); const r2 = await ingestFile(e.ctx, { filePath: p, locationKey: 'raw/clip.mp4', batchId: b });
  assert.notEqual(r1.sourceId, r2.sourceId);
});

test('generated output prefixes and non-videos are refused', async () => {
  const e = await setup(); const b = ensureBatch(e.ctx, 'b');
  const f = makeVideo(path.join(e.raw, 'a.mp4'));
  for (const k of ['review/a.mp4', 'approved/a.mp4', 'previews/a.mp4', 'pending_payment/a.mp4'])
    await assert.rejects(ingestFile(e.ctx, { filePath: f, locationKey: k, batchId: b }), (x) => x instanceof IngestError && x.code === 'NOT_ORIGINAL');
  writeFileSync(path.join(e.raw, 'x.txt'), 'hi');
  await assert.rejects(ingestFile(e.ctx, { filePath: path.join(e.raw, 'x.txt'), locationKey: 'raw/x.txt', batchId: b }), /unsupported/);
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 0);
});

test('move raw -> processed keeps identity; operational cleanup leaves archive playable', async () => {
  const e = await setup();
  makeVideo(path.join(e.raw, 'a.mp4'), { tag: 'mv' });
  await reconcile(e.ctx, { roots: roots(e) });
  const src = e.ctx.db.prepare('select * from sources').get();
  mkdirSync(e.processed, { recursive: true });
  renameSync(path.join(e.raw, 'a.mp4'), path.join(e.processed, 'a.mp4'));
  const rep = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 1, 'no new source after move');
  assert.equal(rep.locations_deactivated, 1);
  const locs = e.ctx.db.prepare("select key,active from source_locations where kind='operational' order by key").all();
  assert.deepEqual(locs.map(l => [l.key, l.active]), [['processed/a.mp4', 1], ['raw/a.mp4', 0]]);
  // production reset: delete every operational file
  rmSync(e.processed, { recursive: true }); rmSync(e.raw, { recursive: true });
  await reconcile(e.ctx, { roots: roots(e) });
  const after = e.ctx.db.prepare('select * from sources where id=?').get(src.id);
  assert.equal(after.sha256, src.sha256); assert.equal(after.ingest_state, 'ready');
  assert.equal((await e.ctx.archive.verify(after.archive_key, after.sha256, after.byte_size)).ok, true);
});

test('batch of 50 with duplicates: every distinct content exactly once, occurrences preserved', async () => {
  const e = await setup();
  for (let i = 0; i < 40; i++) makeVideo(path.join(e.raw, `v${i}.mp4`), { seconds: 1, y: 10 + i, tag: `t${i}` });
  for (let i = 0; i < 10; i++) copyFileSync(path.join(e.raw, `v${i}.mp4`), path.join(e.raw, `dup${i}.mp4`));
  const rep = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(rep.scanned, 50); assert.equal(rep.errors.length, 0);
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 40);
  assert.equal(e.ctx.db.prepare('select count(*) n from upload_occurrences').get().n, 50);
  const again = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(again.skipped, 50, 'second pass is idempotent');
}, { timeout: 120000 });

test('reconcile never imports generated prefixes', async () => {
  const e = await setup();
  const rv = path.join(e.ops = tmp('r-'), 'review');
  makeVideo(path.join(rv, 'reel.mp4'));
  const rep = await reconcile(e.ctx, { roots: [{ dir: rv, prefix: 'review/' }] });
  assert.deepEqual(rep.refused, ['review/reel.mp4']);
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 0);
});

test('truncated (interrupted) upload fails visibly and retries cleanly; never half-registered', async () => {
  const e = await setup(); const f = makeVideo(path.join(e.raw, 'a.mp4'));
  // truncated file => ffprobe cannot read it => INGEST_RETRYABLE/NOT_VIDEO, nothing registered
  const bad = path.join(e.raw, 'partial.mp4'); copyFileSync(f, bad); truncateSync(bad, 500);
  const rep = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(rep.errors.length, 1); assert.match(rep.errors[0].error, /probe failed|INGEST|NOT_VIDEO/);
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 1);
  assert.equal(e.ctx.db.prepare("select state from ingestion_jobs where origin_key='raw/partial.mp4'").get().state, 'failed');
  // upload completes -> next reconcile recovers
  copyFileSync(f, bad); copyFileSync(f, path.join(e.raw, 'z.mp4'));
  const rep2 = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(rep2.errors.length, 0);
  assert.equal(e.ctx.db.prepare("select state from ingestion_jobs where origin_key='raw/partial.mp4'").get().state, 'done');
});

test('lost ingestion event: file never announced is discovered by reconcile', async () => {
  const e = await setup();
  makeVideo(path.join(e.raw, 'late.mp4'), { tag: 'late' });
  assert.equal(e.ctx.db.prepare('select count(*) n from sources').get().n, 0);
  const rep = await reconcile(e.ctx, { roots: roots(e) });
  assert.equal(rep.ingested, 1);
});

test('archive failure is visible (archive_error), not success; reconcile repairs it', async () => {
  const e = await setup(); const f = makeVideo(path.join(e.raw, 'a.mp4'));
  const real = e.ctx.archive.put.bind(e.ctx.archive);
  e.ctx.archive.put = async () => { throw new Error('simulated storage outage'); };
  const r = await ingestFile(e.ctx, { filePath: f, locationKey: 'raw/a.mp4', batchId: ensureBatch(e.ctx, 'b') });
  assert.equal(r.archived, false);
  let s = e.ctx.db.prepare('select * from sources').get();
  assert.equal(s.ingest_state, 'archive_error'); assert.match(s.archive_error, /outage/);
  e.ctx.archive.put = real;
  const rep = await reconcile(e.ctx, { roots: roots(e) });
  s = e.ctx.db.prepare('select * from sources').get();
  assert.equal(s.ingest_state, 'ready'); assert.equal(rep.errors.length, 0);
});

test('hash mismatch on archive copy is rejected and nothing is published', async () => {
  const e = await setup(); const f = makeVideo(path.join(e.raw, 'a.mp4'));
  await assert.rejects(e.ctx.archive.put(f, 'f'.repeat(64), statSync(f).size), /mismatch/);
  assert.equal(existsSync(e.ctx.archive.pathFor(e.ctx.archive.keyFor('f'.repeat(64)))), false);
});

test('archive integrity audit detects corruption and reports it', async () => {
  const e = await setup(); makeVideo(path.join(e.raw, 'a.mp4'));
  await reconcile(e.ctx, { roots: roots(e) });
  const s = e.ctx.db.prepare('select * from sources').get();
  const p = e.ctx.archive.pathFor(s.archive_key); chmodSync(p, 0o644); appendFileSync(p, 'corrupt'); 
  const out = await verifyArchives(e.ctx);
  assert.equal(out.failed.length, 1);
  assert.equal(e.ctx.db.prepare('select ingest_state from sources').get().ingest_state, 'archive_error');
});

test('identity and history are protected by the database itself', async () => {
  const e = await setup(); makeVideo(path.join(e.raw, 'a.mp4'));
  await reconcile(e.ctx, { roots: roots(e) });
  assert.throws(() => e.ctx.db.exec("update sources set sha256='" + 'a'.repeat(64) + "'"), /IMMUTABLE/);
  assert.throws(() => e.ctx.db.exec('delete from sources'), /PROTECTED/);
  assert.throws(() => e.ctx.db.exec('delete from audit_log'), /IMMUTABLE/);
});
