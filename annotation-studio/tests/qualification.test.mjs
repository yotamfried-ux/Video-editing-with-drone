// Phase B end-to-end qualification on SYNTHETIC footage:
//   real pipeline render path -> EDL + predictions export -> Studio: archive (R2 adapter vs stub) -> annotate -> approve
//   -> freeze -> import -> evaluate events + editing -> verify against the actual rendered pixels.
// Skipped when python3/ffmpeg/the pipeline fixture generator is unavailable. Runs on SQLite, or PostgreSQL with STUDIO_TEST_DB_URL.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { newCtx, tmp, BACKEND } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';
import { R2Archive } from '../server/r2archive.mjs';
import { reconcile, verifyArchives } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';
import * as L from '../server/edl.mjs';
import * as I from '../server/imports.mjs';
import { createApp } from '../server/app.mjs';
import { exportBackup, restoreBackup, verifyIntegrity } from '../server/backup.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(here, '..', '..');
const have = c => spawnSync(c, ['-version'], { encoding: 'utf8' }).status === 0 || spawnSync(c, ['--version'], { encoding: 'utf8' }).status === 0;
const skip = process.env.GT_SKIP_QUALIFICATION === '1' || !have('ffmpeg') || !have('python3');

const seg = (id, s, e, o = {}) => ({ id, start_frame: s, end_frame: e, athlete_id: null, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null, ...o });

function bboxAt(sq, n) { const t = n / 30; return { x: (sq.x0 + sq.vx * t) / 3840, y: sq.y / 2160, w: sq.size / 3840, h: sq.size / 2160 }; }
const kfs = (segId, sq, frames) => frames.map(n => ({ id: `${segId}-k${n}`, segment_id: segId, frame: n, bbox: bboxAt(sq, n), visibility: 'visible', origin: 'manual' }));

function whiteCentroid(video, frame) {
  const raw = spawnSync('ffmpeg', ['-loglevel', 'error', '-i', video, '-vf', `select=eq(n\\,${frame}),scale=216:384,format=gray`, '-frames:v', '1', '-f', 'rawvideo', '-'], { maxBuffer: 1e8 }).stdout;
  let sx = 0, sy = 0, n = 0;
  for (let i = 0; i < raw.length; i++) if (raw[i] > 150) { sx += i % 216; sy += Math.floor(i / 216); n++; }
  return n ? { x: (sx / n + 0.5) * 10, y: (sy / n + 0.5) * 10, n } : null;
}

test('Phase B qualification: pipeline exports -> archive -> annotation -> evaluation of the real rendered reels', { skip, timeout: 600000 }, async () => {
  // 1. real pipeline render + exports (separate process, no Studio code, no GT)
  const out = tmp('qual-');
  const gen = spawnSync('python3', [path.join(REPO, 'scripts', 'qualify_gt_export.py'), out], { encoding: 'utf8', cwd: REPO, timeout: 400000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } });
  assert.equal(gen.status, 0, gen.stderr.slice(-1500));
  const truth = JSON.parse(readFileSync(path.join(out, 'truth.json'), 'utf8'));
  const predictions = JSON.parse(readFileSync(path.join(out, 'predictions.v1.json'), 'utf8'));
  const edls = Object.fromEntries(['reel1', 'reel2'].map(r => [r, JSON.parse(readFileSync(path.join(out, 'pipeline-debug', 'edl', `${r}.edl.json`), 'utf8'))]));

  // isolation: exported evidence contains no ground truth
  for (const blob of [JSON.stringify(predictions), JSON.stringify(edls)]) for (const k of ['reviewed_ranges', 'keyframes":[{"id', 'operator', 'annotation_revisions', 'frozen']) assert.ok(!blob.includes(k), `export leaks "${k}"`);
  assert.equal(predictions.pipeline_commit, '0123456789abcdef0123456789abcdef01234567'); assert.equal(predictions.run_id, 'qual-run-001');
  assert.equal(edls.reel1.mode, 'mixed'); assert.equal(edls.reel2.mode, 'tracked_crop');
  assert.deepEqual(edls.reel1.shots.map(s => s.mode), ['tracked_crop', 'contain']);
  assert.equal(edls.reel1.blends[0].out_end - edls.reel1.blends[0].out_start, 12);

  // 2. Studio on the protected-archive backend (R2 adapter vs S3 stub)
  const stub = await startS3Stub();
  const archive = new R2Archive({ endpoint: stub.url, bucket: stub.bucket, accessKeyId: stub.accessKeyId, secretAccessKey: stub.secretAccessKey, multipartThreshold: 100_000 });
  const ctx = newCtx({ archive }); const { db } = ctx;
  const rep = await reconcile(ctx, { roots: [{ dir: path.join(out, 'sources'), prefix: 'raw/' }] });
  assert.equal(rep.errors.length, 0, JSON.stringify(rep.errors)); assert.equal(rep.ingested, 3);
  assert.equal(stub.objects.size, 3, 'originals archived in the protected store');
  const byName = n => db.prepare('select * from sources where display_name=?').get(`${n}.mp4`);
  const S = { srcA: byName('srcA'), srcB: byName('srcB'), srcC: byName('srcC') };
  for (const s of Object.values(S)) assert.equal(s.ingest_state, 'ready');
  // lineage: the hash the pipeline wrote into the EDL is the catalog identity of the archived original
  assert.equal(edls.reel1.shots[0].source_sha256, S.srcA.sha256); assert.equal(edls.reel2.shots[0].source_sha256, S.srcC.sha256);

  // 3. human ground truth (annotated from the analytic truth), approved
  const ath = Object.fromEntries(['A', 'B', 'C'].map(k => [k, A.createAthlete(db, `athlete-${k}`)]));
  const decoyAth = A.createAthlete(db, 'featured-decoy');
  const frames = [0, 30, 60, 90, 104, 119];
  const gt = {
    srcA: c => { c.segments.push(seg('a1', 0, 105, { athlete_id: ath.A.id, framing_mode: 'geometric_center' }), seg('a2', 105, 117, { athlete_id: ath.A.id }));
      c.keyframes.push(...kfs('a1', truth.sources.srcA.squares[0], [0, 30, 60, 90, 104])); },
    srcB: c => { c.segments.push(seg('b1', 0, 120, { athlete_id: ath.B.id })); c.keyframes.push(...kfs('b1', truth.sources.srcB.squares[0], frames)); },
    srcC: c => { c.segments.push(seg('c1', 0, 120, { athlete_id: decoyAth.id, framing_mode: 'geometric_center' })); c.keyframes.push(...kfs('c1', truth.sources.srcC.squares[1], frames)); },
  };
  for (const [name, build] of Object.entries(gt)) {
    const c = A.emptyContent(); build(c); c.reviewed_ranges.push({ start_frame: 0, end_frame: 120 });
    A.saveDraft(db, S[name].id, 0, c); A.approve(db, S[name].id, { expectedVersion: 1 });
  }
  const ds = D.freezeDataset(db, { name: 'qual-v1', sourceIds: Object.values(S).map(s => s.id), policy: { seed: 'q', ratios: { train: 0, validation: 0, test: 1 } } });

  // 4. event evaluation from the real prediction export
  const imp = I.importPipelinePredictions(db, predictions);
  assert.deepEqual(imp.unmatched_sources, []);
  assert.equal(I.importPipelinePredictions(db, predictions).duplicate, true, 'import is idempotent');
  const ev = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: imp.id });
  assert.equal(ev.report.totals.matched, 3); assert.equal(ev.report.pipeline_version, '0123456789ab');
  assert.equal(ev.report.totals.missed, 1, 'the operator-marked wave the pipeline rejected');
  assert.equal(ev.report.totals.missed_but_rejected, 1, 'diagnosed as a pipeline REJECTION (failed_takeoff), not a detection miss');
  const missed = ev.report.per_source.flatMap(p => p.errors).find(e => e.type === 'missed_event');
  assert.equal(missed.pipeline_rejected, 'failed_takeoff');
  assert.equal(E.runEvaluation(db, { dataset_id: ds.id, prediction_id: imp.id }).digest, ev.digest, 'event evaluation is reproducible');

  // 5. editing evaluation from the real EDLs
  const i1 = I.importEdl(db, edls.reel1), i2 = I.importEdl(db, edls.reel2);
  assert.deepEqual([i1.unresolved_sources, i2.unresolved_sources], [[], []]);
  assert.equal(I.importEdl(db, edls.reel1).duplicate, true);
  const g1 = I.gtBySha(db, edls.reel1), g2 = I.gtBySha(db, edls.reel2);
  const r1 = L.evaluateEditing(edls.reel1, { bySha: g1.bySha }), r2 = L.evaluateEditing(edls.reel2, { bySha: g2.bySha });
  assert.equal(r1.status, 'EVALUATED'); assert.equal(r1.mapping, 'verified'); assert.equal(r1.mode, 'mixed');
  assert.equal(r1.coverage.blend_frames, 12, 'cross-dissolve frames are never attributed or scored');
  assert.ok(r1.visibility.fully_visible >= 0.98, `follow crop keeps the athlete in frame (${r1.visibility.fully_visible})`);
  assert.ok(r1.centering.scored_frames > 50 && r1.centering.median < 0.08 && r1.centering.p95 < 0.2, JSON.stringify(r1.centering));
  assert.ok(r1.not_centering_scored_frames > 50, 'the contain shot is not scored against a centre target');
  assert.ok(!r1.errors.some(e => ['missing_surfer', 'wrong_surfer'].includes(e.type)), 'correct reel has no identity/visibility defects');
  // reel2: pipeline followed athlete #1, the operator-truth featured athlete is #2
  assert.equal(r2.status, 'EVALUATED');
  const miss = r2.errors.filter(e => e.type === 'missing_surfer'), wrong = r2.errors.filter(e => e.type === 'wrong_surfer');
  // the decoy only crosses the follow-crop window mid-clip, so most (not all) frames lack the featured athlete
  assert.ok(miss.length >= 60 && r2.visibility.fully_visible < 0.5, `featured athlete mostly absent: missing=${miss.length} visibility=${JSON.stringify(r2.visibility)}`);
  assert.ok(wrong.length > 5, 'identity mismatch is detected from the pipeline subject track');
  assert.equal(miss[0].src_frame, miss[0].out_frame, 'exact output->source frame mapping from the EDL');

  // 6. the Studio's numbers agree with the ACTUAL rendered pixels (not just with the EDL)
  const ev1 = L.frameEvidence(edls.reel1, { bySha: g1.bySha }).frames;
  for (const f of [40, 80, 160, 200]) {
    const row = ev1.find(x => x.f === f), px = whiteCentroid(path.join(out, 'outputs', 'reel1.mp4'), f);
    assert.ok(row.reviewed && px, `frame ${f} reviewed and visible`);
    const cx = (row.box.x1 + row.box.x2) / 2, cy = (row.box.y1 + row.box.y2) / 2;
    assert.ok(Math.abs(cx - px.x) <= 30 && Math.abs(cy - px.y) <= 30, `frame ${f} (${row.mode}): Studio predicts (${cx | 0},${cy | 0}), render shows (${px.x | 0},${px.y | 0})`);
  }

  // 7. through the authenticated API, reproducible and stored immutably
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`, H = { authorization: 'Bearer test-token', 'content-type': 'application/json' };
  try {
    const post = async () => (await fetch(`${base}/api/editing/evaluate`, { method: 'POST', headers: H, body: JSON.stringify({ edl_id: i1.id }) })).json();
    const a = await post(), b = await post();
    assert.equal(JSON.stringify(a.report), JSON.stringify(b.report), 'editing report is deterministic');
    const review = await (await fetch(`${base}/api/outputs/${i1.id}/review`, { headers: H })).json();
    assert.equal(review.verified, true); assert.equal(Object.keys(review.sources).length, 2); assert.equal(review.unresolved.length, 0);
    assert.ok(review.frames.some(f => f.blend) && review.frames.some(f => f.mode === 'contain') && review.frames.some(f => f.mode === 'tracked_crop'));
    assert.ok(!JSON.stringify(review).includes(stub.secretAccessKey));
  } finally { server.closeAllConnections(); server.close(); }

  // 8. operational reset cannot affect Ground Truth, archive, or evaluations
  rmSync(path.join(out, 'sources'), { recursive: true, force: true });
  await reconcile(ctx, { roots: [{ dir: path.join(out, 'sources'), prefix: 'raw/' }] });
  assert.equal((await verifyArchives(ctx)).failed.length, 0, 'archived originals intact after the operational files are gone');
  assert.equal(E.runEvaluation(db, { dataset_id: ds.id, prediction_id: imp.id }).digest, ev.digest);
  assert.ok(verifyIntegrity(db).ok);
  // 9. backup -> restore reproduces the same evaluation
  const fresh = newCtx({ archive });
  restoreBackup(fresh.db, JSON.parse(JSON.stringify(exportBackup(db))));
  assert.equal(E.runEvaluation(fresh.db, { dataset_id: ds.id, prediction_id: imp.id }).digest, ev.digest, 'identical report after restore');
  stub.close();
  void BACKEND; void readdirSync;
});
