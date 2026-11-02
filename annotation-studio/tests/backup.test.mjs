// Backup / restore / integrity (runs on SQLite by default and on PostgreSQL when STUDIO_TEST_DB_URL is set).
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf, BACKEND } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';
import { exportBackup, restoreBackup, verifyBackupFile, verifyIntegrity } from '../server/backup.mjs';

async function populated() {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), { seconds: 2, tag: 'bk' });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const src = ctx.db.prepare('select * from sources').get();
  const ath = A.createAthlete(ctx.db, 'S');
  const c = A.emptyContent(); c.segments.push(seg('s', 3, 40, { athlete_id: ath.id })); c.keyframes.push(kf('k', 's', 5, { x: .1, y: .1, w: .1, h: .1 })); c.reviewed_ranges.push({ start_frame: 0, end_frame: 50 });
  A.saveDraft(ctx.db, src.id, 0, c); A.approve(ctx.db, src.id, { expectedVersion: 1 });
  const ds = D.freezeDataset(ctx.db, { name: 'd', sourceIds: [src.id], policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
  const pr = E.importPredictions(ctx.db, { run_id: 'r', pipeline_version: 'v', sources: [{ source_sha256: src.sha256, events: [{ start_frame: 4, end_frame: 39 }] }] });
  E.runEvaluation(ctx.db, { dataset_id: ds.id, prediction_id: pr.id });
  return { ctx, src };
}

test('backup -> restore into an empty database reproduces every table exactly', async () => {
  const { ctx } = await populated();
  const b = exportBackup(ctx.db);
  assert.deepEqual(verifyBackupFile(b), []);
  assert.ok(b.counts.annotation_revisions === 1 && b.counts.evaluation_runs === 1 && b.counts.sources === 1);
  const fresh = newCtx();
  const r = restoreBackup(fresh.db, JSON.parse(JSON.stringify(b)));
  assert.equal(r.digest, b.digest);
  const again = exportBackup(fresh.db);
  for (const t of Object.keys(b.tables)) if (t !== 'audit_log') assert.deepEqual(again.tables[t], b.tables[t], t);
  assert.ok(verifyIntegrity(fresh.db).ok);
  // restored DB keeps working: new audit rows / identity ids do not collide
  A.createAthlete(fresh.db, 'after-restore');
});

test('a tampered or truncated backup file is refused; restore never merges into live data', async () => {
  const { ctx } = await populated();
  const b = JSON.parse(JSON.stringify(exportBackup(ctx.db)));
  b.tables.annotation_revisions[0].reason = 'edited';
  assert.ok(verifyBackupFile(b).includes('digest_mismatch'));
  assert.throws(() => restoreBackup(newCtx().db, b), /failed verification/);
  const t = JSON.parse(JSON.stringify(exportBackup(ctx.db))); t.tables.sources = [];
  assert.ok(verifyBackupFile(t).some(p => p.startsWith('count_mismatch') || p === 'digest_mismatch'));
  assert.throws(() => restoreBackup(ctx.db, exportBackup(ctx.db)), /non-empty/);
});

test('integrity audit recomputes digests and exposes silent tampering', { skip: BACKEND !== 'sqlite' }, async () => {
  const { ctx } = await populated();
  assert.ok(verifyIntegrity(ctx.db).ok);
  // bypass the append-only triggers the way a direct file edit would
  ctx.db.exec('drop trigger annotation_revisions_no_update');
  ctx.db.prepare("update annotation_revisions set content=replace(content,'\"start_frame\":3','\"start_frame\":4')").run();
  const r = verifyIntegrity(ctx.db);
  assert.equal(r.ok, false); assert.equal(r.problems[0].table, 'annotation_revisions');
});
