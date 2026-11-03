// Local-first independent backup: same-device refusal, labelled scope, self-repair, visible failure, full restore drill, status.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { chmodSync, existsSync, readdirSync, readFileSync, writeFileSync, appendFileSync, statSync } from 'node:fs';
import { newCtx, makeVideo, tmp, seg, BACKEND } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import { runOffsiteBackup, verifyOffsite, restoreFromOffsite, backupStatus, BackupError, plaintextArtifacts } from '../server/offsite.mjs';
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
// Legacy plaintext layout is only allowed with an explicit "the destination disk is fully encrypted" attestation.
const diffDev = ctx => ({ deviceOf: otherDevice(ctx.home), diskOf: () => null, plaintext: 'device-encrypted' });
const KEY = 'correct horse battery staple 2026';
const encDev = ctx => ({ deviceOf: otherDevice(ctx.home), diskOf: () => null, encryption_key: KEY });

test('refuses a destination on the same physical device as the live data', async () => {
  const { ctx } = await world();
  const dest = tmp('same-disk-');                                     // /tmp and the Studio home share one filesystem here
  await assert.rejects(runOffsiteBackup(ctx, dest, { encryption_key: KEY }), e => e instanceof BackupError && e.code === 'BACKUP_SAME_DEVICE');
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


test('encryption is mandatory: no key and no device-encryption attestation -> refused before anything is written; weak keys refused', async () => {
  const { ctx } = await world();
  const dest = tmp('ext-');
  await assert.rejects(runOffsiteBackup(ctx, dest, { deviceOf: otherDevice(ctx.home), diskOf: () => null }), e => e.code === 'BACKUP_ENCRYPTION_REQUIRED');
  await assert.rejects(runOffsiteBackup(ctx, dest, { deviceOf: otherDevice(ctx.home), diskOf: () => null, encryption_key: 'short' }), e => e.code === 'BACKUP_KEY_WEAK');
  assert.deepEqual(readdirSync(dest), []);
});

test('a different volume on the SAME physical disk is refused; distinct disks are recorded as such', async () => {
  const { ctx } = await world();
  const dest = tmp('ext-');
  await assert.rejects(runOffsiteBackup(ctx, dest, { ...encDev(ctx), diskOf: () => 'disk0' }), e => e.code === 'BACKUP_SAME_DISK');
  const r = await runOffsiteBackup(ctx, dest, { ...encDev(ctx), diskOf: p => (String(p).startsWith(dest) ? 'disk1' : 'disk0') });
  assert.equal(r.device_check, 'distinct_physical_disk');
  const r2 = await runOffsiteBackup(ctx, tmp('ext-'), encDev(ctx));
  assert.equal(r2.device_check, 'volume_only', 'unknown disk identity is reported honestly, never as a separate disk');
});

test('ENCRYPTED backup: nothing readable on the medium — DB export, SQLite snapshot and footage are all ciphertext', async () => {
  const { ctx, a } = await world();
  const dest = tmp('ext-enc-');
  const r = await runOffsiteBackup(ctx, dest, { ...encDev(ctx), scope: 'all' });
  assert.equal(r.ok, true); assert.equal(r.encrypted, true); assert.equal(r.copied, 2);
  // SQLite backend: the physical snapshot is encrypted; PostgreSQL has no file snapshot (logical export only).
  if (BACKEND === 'sqlite') assert.ok(r.sqlite_file.endsWith('.sqlite.enc')); else assert.equal(r.sqlite_file, undefined);
  assert.deepEqual(plaintextArtifacts(dest), [], 'no plaintext artifact on the backup medium');
  const original = readFileSync(ctx.archive.pathFor(a.archive_key));
  const needle = original.subarray(original.length >> 1, (original.length >> 1) + 64);
  const walk = d => readdirSync(d).flatMap(n => { const p = path.join(d, n); return statSync(p).isDirectory() ? walk(p) : [p]; });
  for (const f of walk(dest)) {
    const buf = readFileSync(f);
    assert.equal(buf.includes(needle), false, `footage bytes leaked into ${path.basename(f)}`);
    assert.equal(buf.includes(Buffer.from('SQLite format 3')), false, `plaintext SQLite in ${path.basename(f)}`);
    assert.equal(buf.includes(Buffer.from(a.sha256)), false, `footage hash leaked in ${path.basename(f)}`);
    assert.equal(buf.includes(Buffer.from(KEY)), false, 'key never written');
  }
  // no plaintext snapshot left behind in the live home either
  assert.deepEqual(readdirSync(ctx.home).filter(n => n.startsWith('.backup-work-')), []);
});

test('ENCRYPTED backup: wrong key, missing key and tampering are clear failures; a rerun with another key is refused', async () => {
  const { ctx } = await world();
  const dest = tmp('ext-enc-');
  await runOffsiteBackup(ctx, dest, encDev(ctx));
  const noKey = await verifyOffsite(dest);
  assert.equal(noKey.ok, false); assert.ok(noKey.problems.includes('encryption_key_required'));
  const wrong = await verifyOffsite(dest, { encryption_key: 'definitely the wrong key' });
  assert.ok(wrong.problems.includes('encryption_key_wrong'));
  await assert.rejects(restoreFromOffsite(newCtx(), dest, { encryption_key: 'definitely the wrong key' }), e => e.code === 'BACKUP_KEY_WRONG');
  await assert.rejects(runOffsiteBackup(ctx, dest, { ...encDev(ctx), encryption_key: 'another sufficiently long key' }), e => e.code === 'BACKUP_KEY_MISMATCH');
  assert.equal((await verifyOffsite(dest, { encryption_key: KEY })).ok, true);
  // flip one ciphertext byte inside a footage object
  const obj = readdirSync(path.join(dest, 'objects')).find(n => n.endsWith('.enc'));
  const f = path.join(dest, 'objects', obj); chmodSync(f, 0o644);
  const buf = readFileSync(f); buf[buf.length >> 1] ^= 0xff; writeFileSync(f, buf);
  const v = await verifyOffsite(dest, { encryption_key: KEY });
  assert.equal(v.ok, false); assert.match(v.problems.join(), /cipher_mismatch|BACKUP_KEY_OR_DATA_INVALID/);
  const fresh = newCtx();
  await assert.rejects(restoreFromOffsite(fresh, dest, { encryption_key: KEY }), e => e.code === 'BACKUP_UNVERIFIED');
  assert.equal(fresh.db.prepare('select count(*) n from sources').get().n, 0, 'never half-restored');
  // the next run detects the damaged copy and repairs it from the verified original
  const r = await runOffsiteBackup(ctx, dest, encDev(ctx));
  assert.equal(r.repaired, 1); assert.equal((await verifyOffsite(dest, { encryption_key: KEY })).ok, true);
});

test('ENCRYPTED RESTORE DRILL after "restart": every surfer, video, owner assignment, history, event, box and revision is back', async () => {
  const { ctx, a, b } = await world();
  // richer state: owner assignment with history, a bound box verification, a second draft
  const Catalog = await import('../server/catalog_owner.mjs');
  const ath = A.createAthlete(ctx.db, 'Owner');
  Catalog.setCatalogOwner(ctx.db, b.id, { owner_athlete_id: ath.id, expected_version: 0 });
  const c = A.getDraft(ctx.db, a.id).content;
  c.keyframes.push({ id: 'k', segment_id: 's', frame: 10, bbox: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }, visibility: 'visible', origin: 'manual', verification_status: 'verified_correct' });
  c.box_verifications = [{ segment_id: 's', frame: 10, status: 'verified_correct', bbox: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }, athlete_id: c.segments[0].athlete_id, verified_by: 'op', verified_at: '2026-11-01T00:00:00.000Z' }];
  A.saveDraft(ctx.db, a.id, A.getDraft(ctx.db, a.id).version, c);
  const dest = tmp('ext-enc-');
  assert.equal((await runOffsiteBackup(ctx, dest, { ...encDev(ctx), scope: 'all' })).ok, true);
  const before = exportBackup(ctx.db);
  ctx.db.close?.();                                                     // the live machine is gone
  const fresh = newCtx();
  const out = await restoreFromOffsite(fresh, dest, { encryption_key: KEY });
  assert.equal(out.restored_objects, 2); assert.equal(out.unavailable_sources, 0);
  const after = exportBackup(fresh.db);
  for (const t of ['sources', 'athletes', 'athlete_appearances', 'annotation_drafts', 'annotation_revisions', 'source_owner_history', 'sports', 'sport_event_types']) {
    assert.equal(JSON.stringify(after.tables[t]?.map(r => ({ ...r, thumb_path: undefined, proxy_path: undefined }))), JSON.stringify(before.tables[t]?.map(r => ({ ...r, thumb_path: undefined, proxy_path: undefined }))), t);
  }
  assert.equal(fresh.db.prepare('select owner_athlete_id from sources where id=?').get(b.id).owner_athlete_id, ath.id);
  assert.equal(A.sourceStates(fresh.db, a.id).box_qa.frames_verified, 1);
  for (const s of fresh.db.prepare('select * from sources').all()) assert.equal((await fresh.archive.verify(s.archive_key, s.sha256, s.byte_size)).ok, true);
  // The export is taken before the run is logged, so a restored machine honestly reports "no backup yet" and the UI
  // prompts for a fresh backup of the rebuilt machine (it never inherits a claim about a different machine's state).
  assert.equal(backupStatus(fresh.db).state, 'never');
});

test('review#10: manifest re-pointing is detected (keyed MAC); plaintext run into an encrypted destination refused; plaintext leftovers fail verify', async () => {
  const { ctx } = await world();
  const dest = tmp('ext-enc-');
  await runOffsiteBackup(ctx, dest, encDev(ctx));
  const mf = path.join(dest, 'MANIFEST.json');
  const m = JSON.parse(readFileSync(mf, 'utf8'));
  // attacker without the key recomputes the plain digest after re-pointing
  const { digest, mac, ...body } = m; body.db_file = 'gt-older.json.enc';
  const { digestOf } = await import('../server/annotations.mjs');
  writeFileSync(mf, JSON.stringify({ ...body, digest: digestOf(body), mac }));
  assert.ok((await verifyOffsite(dest, { encryption_key: KEY })).problems.includes('manifest_mac_mismatch'));
  await assert.rejects(runOffsiteBackup(ctx, dest, diffDev(ctx)), e => e.code === 'BACKUP_MODE_MISMATCH');
  const dest2 = tmp('ext-enc-'); await runOffsiteBackup(ctx, dest2, encDev(ctx));
  writeFileSync(path.join(dest2, 'db', 'leftover.json'), '{}');
  const v = await verifyOffsite(dest2, { encryption_key: KEY });
  assert.equal(v.ok, false); assert.match(v.problems.join(), /plaintext_artifacts_present/);
});
