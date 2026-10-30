// M4: dataset freezing, blind evaluation, determinism, isolation.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';

async function world(n = 4) {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  for (let i = 0; i < n; i++) makeVideo(path.join(raw, `v${i}.mp4`), { seconds: 3, y: 10 + i * 20, tag: `e${i}` });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  return { ctx, db: ctx.db, srcs: ctx.db.prepare('select * from sources order by display_name').all() };
}
function approveWith(db, src, build) {
  const c = A.emptyContent(); build(c); A.saveDraft(db, src.id, A.getDraft(db, src.id).version, c);
  return A.approve(db, src.id, { expectedVersion: A.getDraft(db, src.id).version, acknowledgeUnresolved: true }).revision;
}

test('freeze is immutable, pins exact revision, and later edits do not change it', async () => {
  const { db, srcs } = await world(3);
  for (const s of srcs) approveWith(db, s, c => c.segments.push(seg('a', 5, 40)));
  const ds = D.freezeDataset(db, { name: 'v1', sourceIds: srcs.map(s => s.id) });
  const before = db.prepare('select digest from dataset_versions where id=?').get(ds.id).digest;
  const c = A.getDraft(db, srcs[0].id).content; c.segments[0].end_frame = 60;
  A.saveDraft(db, srcs[0].id, 1, c); A.approve(db, srcs[0].id, { expectedVersion: 2, acknowledgeUnresolved: true });
  assert.equal(db.prepare('select digest from dataset_versions where id=?').get(ds.id).digest, before);
  assert.throws(() => db.prepare("update dataset_members set split='train'").run(), /IMMUTABLE/);
  const m = db.prepare('select revision_id from dataset_members where source_id=?').get(srcs[0].id);
  assert.equal(A.getRevision(db, m.revision_id).seq, 1, 'dataset still points at revision 1');
});

test('splits are deterministic, group-consistent, and the held-out test set is permanent', async () => {
  const { db, srcs } = await world(4);
  db.prepare("update sources set session_key='same-day' where id in (?,?)").run(srcs[0].id, srcs[1].id);
  for (const s of srcs) approveWith(db, s, c => c.segments.push(seg('a', 5, 40)));
  const a = D.freezeDataset(db, { name: 'a', sourceIds: srcs.map(s => s.id) });
  const sp = Object.fromEntries(a.manifest.members.map(m => [m.source_id, m.split]));
  assert.equal(sp[srcs[0].id], sp[srcs[1].id], 'same session shares a split');
  const b = D.freezeDataset(db, { name: 'b', sourceIds: srcs.map(s => s.id), policy: { seed: 'other-seed', ratios: { train: 0.9, validation: 0.05, test: 0.05 } } });
  for (const m of a.manifest.members.filter(m => m.split === 'test')) {
    assert.equal(b.manifest.members.find(x => x.source_id === m.source_id).split, 'test', 'previously held-out stays test');
  }
  const a2 = D.freezeDataset(db, { name: 'a', sourceIds: srcs.map(s => s.id) });
  assert.equal(a2.digest, a.digest, 'same inputs => identical manifest digest');
});

test('freeze refuses sources with no approved revision', async () => {
  const { db, srcs } = await world(1);
  assert.throws(() => D.freezeDataset(db, { name: 'x', sourceIds: [srcs[0].id] }), /אין גרסה מאושרת/);
});

test('matching reports hits, misses, duplicates, wrong athlete, false positives, excluded, unreviewed', () => {
  const gt = { segments: [
    seg('g1', 0, 100, { athlete_id: 'A' }), seg('g2', 200, 300, { athlete_id: 'B' }), seg('g3', 400, 500, { athlete_id: 'A' }),
    seg('g4', 600, 700, { athlete_id: 'A' }), seg('ex', 800, 900, { decision: 'exclude' }),
  ], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 1000 }] };
  const preds = [
    { start_frame: 2, end_frame: 98, athlete_key: 'p1' },     // hit g1 (A<-p1)
    { start_frame: 0, end_frame: 100, athlete_key: 'p1' },    // duplicate of g1
    { start_frame: 205, end_frame: 295, athlete_key: 'p1' },  // matches g2 (B) but mapped to p1->A  => wrong athlete
    { start_frame: 405, end_frame: 495, athlete_key: 'p1' },  // hit g3
    { start_frame: 810, end_frame: 880, athlete_key: 'p1' },  // predicted an excluded event
    { start_frame: 950, end_frame: 990, athlete_key: 'p1' },  // false positive (reviewed, nothing there)
    { start_frame: 1200, end_frame: 1300, athlete_key: 'p1' },// outside reviewed range
  ];
  const r = E.evaluateSource(gt, preds, E.DEFAULT_PARAMS);
  assert.equal(r.matched, 3); assert.equal(r.missed, 1); assert.equal(r.duplicates, 1);
  assert.equal(r.predicted_excluded, 1); assert.equal(r.false_positives, 1); assert.equal(r.unreviewed_predictions, 1);
  assert.equal(r.attributable, 3); assert.equal(r.correct_attribution, 2);
  const types = r.errors.map(e => e.type).sort();
  assert.deepEqual(types, ['duplicate', 'false_positive', 'missed_event', 'predicted_excluded', 'wrong_athlete']);
  assert.equal(r.errors.find(e => e.type === 'missed_event').segment_id, 'g4');
});

test('end-to-end evaluation is reproducible and ignores unreviewed/uncertain in strict scoring', async () => {
  const { db, srcs } = await world(2);
  const ath = A.createAthlete(db, 'S1');
  for (const s of srcs) approveWith(db, s, c => { c.segments.push(seg('a', 10, 50, { athlete_id: ath.id }), seg('u', 60, 80, { decision: 'uncertain' })); c.reviewed_ranges.push({ start_frame: 0, end_frame: 90 }); });
  const ds = D.freezeDataset(db, { name: 'd', sourceIds: srcs.map(s => s.id), policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
  const pr = E.importPredictions(db, { run_id: 'run-1', pipeline_version: 'abc123', sources: srcs.map(s => ({ source_sha256: s.sha256, events: [{ start_frame: 11, end_frame: 49, athlete_key: 'k' }, { start_frame: 62, end_frame: 78, athlete_key: 'k' }] })) });
  const e1 = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pr.id });
  const e2 = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pr.id });
  assert.equal(e1.digest, e2.digest, 'identical report digest on repeat');
  assert.equal(e1.report.metrics.event_recall, 1); assert.equal(e1.report.metrics.event_precision, 1);
  assert.equal(e1.report.totals.uncertain_overlap, 2, 'prediction over an uncertain interval is not scored as a false positive');
  assert.throws(() => db.prepare('update evaluation_runs set report=?').run('{}'), /IMMUTABLE/);
});

test('blind manifest and training export never leak unapproved/inference-forbidden data', async () => {
  const { db, srcs } = await world(2);
  for (const s of srcs) approveWith(db, s, c => c.segments.push(seg('a', 5, 40)));
  const ds = D.freezeDataset(db, { name: 'd', sourceIds: srcs.map(s => s.id), policy: { seed: 's', ratios: { train: 1, validation: 0, test: 0 } } });
  const blind = JSON.stringify(D.blindInferenceManifest(db, ds.id));
  for (const forbidden of ['segment', 'decision', 'athlete', 'bbox', 'start_frame', 'split', 'revision']) assert.ok(!blind.includes(forbidden), `blind manifest leaks ${forbidden}`);
  // unapproved draft edit must not reach export
  const c = A.getDraft(db, srcs[0].id).content; c.segments[0].end_frame = 80; A.saveDraft(db, srcs[0].id, 1, c);
  const lines = D.exportJsonl(db, ds.id, ['train']).trim().split('\n').map(JSON.parse);
  assert.equal(lines.length, 2); assert.ok(lines.every(l => l.annotations.segments[0].end_frame === 40));
});
