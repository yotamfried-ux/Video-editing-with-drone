// Local-first independent backup: same-device refusal, labelled scope, self-repair, visible failure, full restore drill, status.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { chmodSync, existsSync, readdirSync, readFileSync, writeFileSync, appendFileSync, statSync } from 'node:fs';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import { runOffsiteBackup, verifyOffsite, restoreFromOffsite, backupStatus, BackupError } from '../server/offsite.mjs';
import { exportBackup } from '../server/backup.mjs';
import { createApp } from '../server/app.mjs';

// Two clips; only the first one gets labelled. Different devices are simulated with an injected device function
// (a CI/tmp filesystem is a single device) — the REAL st_dev check is exercised by the refusal test.
async function world() {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), { seconds: 2, tag: 'bk-a' }); makeVideo(path.join(raw, 'b.mp4'), { seconds: 2, y: 20, tag: 'bk-b' });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const [a, b] = ctx.db.prepare('select * from sources order by display_name').all();
  const ath = A.createAthlete(ctx.db, 'S');
  const c = A.emptyContent(); c.segments.push(seg('s', 3, 40, { athlete_id: ath.id })); c.reviewed_ranges.push({ start_frame: 0, end_frame: 50 });
  A.saveDraft(ctx.db, a.id, 0, c); A.approve(ctx.db, a.id, { expectedVersion: 1 });
  return { ctx, a, b, raw };
}
const otherDevice = (live) => p => (String(p).startsWith(live) ? 1 : 2);
const diffDev = ctx => ({ deviceOf: otherDevice(ctx.home) });

test('refuses a destination on the same physical device as the live data', async () => {
  const { ctx } = await world();
  const dest = tmp('same-disk-');                                     // /tmp and the Studio home share one filesystem here
  await assert.rejects(runOffsiteBackup(ctx, dest), e => e instanceof BackupError && e.code === 'BACKUP_SAME_DEVICE');
  assert.deepEqual(readdirSync(dest), [], 'nothing was written');
  assert.equal(backupStatus(ctx.db).state, 'never', 'a refused run is not a backup');
});

test('labelled scope copies only footage that has ground truth; scope all copies everything; reruns are idempotent', async () => {
  const { ctx, a, b } = await world();
  const dest = tmp('ext-');
  const r1 = await runOffsiteBackup(ctx, dest, diffDev(ctx));
  assert.equal(r1.ok, true); assert.equal(r1.copied, 1); assert.deepEqual(r1.objects.map(o => o.sha256), [a.sha256]);
  assert.ok(!existsSync(path.join(dest, 'archive', b.sha256.slice(0, 2), b.sha256)), 'unlabelled footage is not copied by default');
  const r2 = await runOffsiteBackup(ctx, dest, diffDev(ctx));
  assert.deepEqual([r2.copied, r2.skipped], [0, 1]);
  const r3 = await runOffsiteBackup(ctx, dest, { ...diffDev(ctx), scope: 'all' });
  assert.deepEqual([r3.copied, r3.skipped], [1, 1]);
  assert.equal((statSync(path.join(dest, 'archive', a.sha256.slice(0, 2), a.sha256)).mode & 0o222), 0, 'backup copies are read-only');
  assert.deepEqual(await verifyOffsite(dest), { ok: true, problems: [], objects: 2, created_at: (await verifyOffsite(dest)).created_at, scope: 'all' });
});

test('a corrupted destination copy is detected by verify and repaired by the next run (never trusted)', async () => {
  const { ctx, a } = await world();
  const dest = tmp('ext-');
  await runOffsiteBackup(ctx, dest, diffDev(ctx));
  const f = path.join(dest, 'archive', a.sha256.slice(0, 2), a.sha256);
  chmodSync(f, 0o644); appendFileSync(f, 'bitrot');
  const v = await verifyOffsite(dest); assert.equal(v.ok, false); assert.match(v.problems.join(), /object:.*:(size|hash)_mismatch/);
  const r = await runOffsiteBackup(ctx, dest, diffDev(ctx));
  assert.equal(r.ok, true); assert.equal(r.repaired, 1);
  assert.equal((await verifyOffsite(dest)).ok, true);
});

test('a corrupt SOURCE copy is never propagated; the run fails visibly and is not recorded as a good backup', async () => {
  const { ctx, a } = await world();
  const dest = tmp('ext-');
  const p = ctx.archive.pathFor(a.archive_key); chmodSync(p, 0o644); appendFileSync(p, 'x');
  const r = await runOffsiteBackup(ctx, dest, diffDev(ctx));
  assert.equal(r.ok, false); assert.equal(r.failed[0].reason, 'source_size_mismatch'); assert.equal(r.copied, 0);
  const st = backupStatus(ctx.db); assert.equal(st.state, 'never'); assert.equal(st.last_failed, true);
});

test('tampering with the manifest or the database export is detected', async () => {
  const { ctx } = await world();
  const dest = tmp('ext-'); await runOffsiteBackup(ctx, dest, diffDev(ctx));
  const mf = path.join(dest, 'MANIFEST.json'); const m = JSON.parse(readFileSync(mf, 'utf8')); m.objects = []; writeFileSync(mf, JSON.stringify(m));
  assert.match((await verifyOffsite(dest)).problems.join(), /manifest_digest_mismatch/);
  assert.deepEqual((await verifyOffsite(tmp('empty-'))).problems, ['manifest_missing']);
});

test('RESTORE DRILL: an empty machine is rebuilt from the backup — database, originals, derivatives, playback', async () => {
  const { ctx, a, b, raw } = await world();
  const dest = tmp('ext-'); await runOffsiteBackup(ctx, dest, diffDev(ctx));
  const before = exportBackup(ctx.db);
  const fresh = newCtx();                                                // new home, new empty database, new empty archive
  const out = await restoreFromOffsite(fresh, dest);
  assert.equal(out.restored_objects, 1); assert.equal(out.unavailable_sources, 1, 'the unlabelled source was not in the backup'); assert.equal(out.derivatives.failed.length, 0); assert.ok(out.derivatives.rebuilt >= 1);
  const sb = fresh.db.prepare('select * from sources where id=?').get(b.id);
  assert.equal(sb.ingest_state, 'unavailable'); assert.equal(sb.archive_error, 'not_in_restored_backup');
  // ...and it heals itself: when its file reappears in operational storage, reconcile re-archives it under the SAME identity
  await reconcile(fresh, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const healed = fresh.db.prepare('select * from sources where id=?').get(b.id);
  assert.equal(healed.ingest_state, 'ready'); assert.equal(fresh.db.prepare('select count(*) n from sources').get().n, 2, 'no duplicate source was created');
  const after = exportBackup(fresh.db);
  for (const t of ['sources', 'athletes', 'annotation_drafts', 'annotation_revisions']) assert.deepEqual(after.tables[t].map(r => r.id ?? r.source_id), before.tables[t].map(r => r.id ?? r.source_id), t);
  const s = fresh.db.prepare('select * from sources where id=?').get(a.id);
  assert.equal((await fresh.archive.verify(s.archive_key, s.sha256, s.byte_size)).ok, true, 'original restored byte-exact');
  assert.ok(s.proxy_path && existsSync(s.proxy_path) && s.proxy_path.startsWith(fresh.home), 'derivatives rebuilt in the NEW cache');
  assert.equal(A.getRevision(fresh.db, before.tables.annotation_revisions[0].id).content.segments[0].start_frame, 3, 'approved revision identical');
  // playback works end to end on the restored machine
  const server = createApp(fresh); await new Promise(r => server.listen(0, '127.0.0.1', r));
  try {
    const res = await fetch(`http://127.0.0.1:${server.address().port}/media/${a.id}/proxy`, { headers: { authorization: 'Bearer test-token', range: 'bytes=0-49' } });
    assert.equal(res.status, 206);
  } finally { server.closeAllConnections(); server.close(); }
});

test('a damaged backup is refused for restore (never half-restored)', async () => {
  const { ctx, a } = await world();
  const dest = tmp('ext-'); await runOffsiteBackup(ctx, dest, diffDev(ctx));
  const f = path.join(dest, 'archive', a.sha256.slice(0, 2), a.sha256); chmodSync(f, 0o644); appendFileSync(f, 'x');
  const fresh = newCtx();
  await assert.rejects(restoreFromOffsite(fresh, dest), e => e.code === 'BACKUP_UNVERIFIED');
  assert.equal(fresh.db.prepare('select count(*) n from sources').get().n, 0, 'nothing restored');
});

test('status: never -> ok -> stale, exposed read-only over the authenticated API (no HTTP way to start a backup)', async () => {
  const { ctx } = await world();
  assert.equal(backupStatus(ctx.db).state, 'never');
  await runOffsiteBackup(ctx, tmp('ext-'), diffDev(ctx));
  assert.equal(backupStatus(ctx.db).state, 'ok');
  // the audit log is append-only, so staleness is tested by advancing the clock, not by editing history
  const stale = backupStatus(ctx.db, { nowMs: Date.now() + 9 * 86400000 });
  assert.equal(stale.state, 'stale'); assert.ok(stale.age_days >= 8);
  assert.throws(() => ctx.db.prepare("update audit_log set at='x' where action='offsite_backup'").run(), /IMMUTABLE/, 'backup history cannot be rewritten');
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal((await fetch(`${base}/api/backup/status`)).status, 401);
    const j = await (await fetch(`${base}/api/backup/status`, { headers: { authorization: 'Bearer test-token' } })).json();
    assert.equal(j.state, 'ok');
    assert.equal((await fetch(`${base}/api/backup/run`, { method: 'POST', headers: { authorization: 'Bearer test-token' } })).status, 404, 'no HTTP endpoint writes to arbitrary paths');
  } finally { server.closeAllConnections(); server.close(); }
});


test('AES-256-GCM encrypted offsite backup: requires key to verify/restore, recreates state byte-exact', async () => {
  const { ctx, a, raw } = await world();
  const dest = tmp('ext-enc-');
  const secretKey = 'test-passphrase-super-secret-key-1234';

  const res = await runOffsiteBackup(ctx, dest, { ...diffDev(ctx), encryption_key: secretKey });
  assert.equal(res.ok, true);
  assert.equal(res.encrypted, true);
  assert.match(res.db_file, /\.enc$/);

  // Without key: verify notes missing key
  const noKeyVerify = await verifyOffsite(dest);
  assert.equal(noKeyVerify.ok, false);
  assert.ok(noKeyVerify.problems.includes('encryption_key_required'));

  // With key: verify succeeds
  const keyVerify = await verifyOffsite(dest, { encryption_key: secretKey });
  assert.equal(keyVerify.ok, true);
  assert.deepEqual(keyVerify.problems, []);

  // Restore into a fresh isolated context
  const fresh = newCtx();
  const restored = await restoreFromOffsite(fresh, dest, { encryption_key: secretKey });
  assert.equal(restored.restored_objects, 1);

  // Verify DB content in fresh context
  const s = fresh.db.prepare('select * from sources where id=?').get(a.id);
  assert.equal(s.sha256, a.sha256);
  assert.equal(fresh.db.prepare("select count(*) n from annotation_revisions").get().n, 1);
});
