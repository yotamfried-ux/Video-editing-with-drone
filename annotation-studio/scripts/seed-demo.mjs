// Builds a demo STUDIO_HOME from SYNTHETIC footage only (no real/production data, no network).
//   node scripts/seed-demo.mjs [home]   (default: ./.demo-home)
import path from 'node:path';
import { rmSync, mkdirSync, copyFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createContext } from '../server/context.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';
import * as L from '../server/edl.mjs';
import { makeVideo } from './synthetic.mjs';

export async function seed(home, { quiet = false } = {}) {
  rmSync(home, { recursive: true, force: true });
  const ctx = createContext(home, { token: process.env.STUDIO_TOKEN ?? 'demo-token' });
  const ops = path.join(home, 'operational'), raw = path.join(ops, 'raw'), processed = path.join(ops, 'processed');
  const specs = [['DJI_0412.mp4', 70, 'd1'], ['DJI_0413.mp4', 200, 'd2'], ['DJI_0414.mp4', 330, 'd3'], ['DJI_0415.mp4', 450, 'd4']];
  for (const [n, y, tag] of specs) makeVideo(path.join(raw, n), { seconds: 8, w: 1280, h: 720, y, tag });
  mkdirSync(processed, { recursive: true });
  copyFileSync(path.join(raw, 'DJI_0413.mp4'), path.join(processed, 'DJI_0413_copy.mp4')); // same bytes, other name
  const roots = [{ dir: raw, prefix: 'raw/' }, { dir: processed, prefix: 'processed/' }];
  const rep = await reconcile(ctx, { roots, batchLabel: 'אצווה 2026-10-30 (דמו)' });
  if (!quiet) console.log('reconcile', JSON.stringify({ ingested: rep.ingested, duplicates: rep.duplicates, errors: rep.errors }));
  ctx.roots = roots;
  const db = ctx.db;
  const byName = n => db.prepare('select * from sources where display_name=?').get(n);
  const s1 = byName('DJI_0412.mp4'), s2 = byName('DJI_0413.mp4');

  const dana = A.createAthlete(db, 'גולש #1 — דנה'), omer = A.createAthlete(db, 'גולש #2 — עומר');
  // s1: two approved revisions with overlapping events, exclusion, uncertainty and bbox keyframes
  // surfer box (normalized): x=2n/1280, y=70/720, w=40/1280, h=40/720  (analytic truth)
  const bb = n => ({ x: 2 * n / 1280, y: 70 / 720, w: 40 / 1280, h: 40 / 720 });
  const c = A.emptyContent();
  c.segments.push(
    { id: 'seg-wave1', start_frame: 20, end_frame: 160, athlete_id: dana.id, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: 'גל מלא', framing_mode: 'geometric_center', target: null },
    { id: 'seg-fail', start_frame: 170, end_frame: 200, athlete_id: omer.id, event_type: 'failed_takeoff', decision: 'exclude', reason_code: 'failed_takeoff', notes: 'עמידה נכשלה', framing_mode: null, target: null });
  c.keyframes.push(...[20, 90, 159].map((n, i) => ({ id: `kf-${i}`, segment_id: 'seg-wave1', frame: n, bbox: bb(n), visibility: 'visible', origin: 'manual' })));
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 200 });
  A.saveDraft(db, s1.id, 0, c);
  A.approve(db, s1.id, { expectedVersion: 1, reason: 'סימון ראשוני' });
  c.segments.push({ id: 'seg-wave2', start_frame: 205, end_frame: 235, athlete_id: omer.id, event_type: 'wave_ride', decision: 'uncertain', reason_code: null, notes: 'לא ברור אם הגל הושלם', framing_mode: null, target: null });
  A.saveDraft(db, s1.id, 1, c);
  A.approve(db, s1.id, { expectedVersion: 2, reason: 'נוסף אירוע לא בטוח', acknowledgeUnresolved: true });
  // s2: draft in progress only
  const c2 = A.emptyContent(); c2.segments.push({ id: 'x', start_frame: 40, end_frame: 120, athlete_id: null, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null });
  A.saveDraft(db, s2.id, 0, c2);

  const ds = D.freezeDataset(db, { name: 'GT-v1 (דמו)', sourceIds: [s1.id], policy: { seed: 'demo', ratios: { train: 0, validation: 0, test: 1 } } });
  const pred = E.importPredictions(db, { run_id: 'demo-run-001', pipeline_version: 'pipeline@demo', sources: [{ source_sha256: s1.sha256, events: [
    { start_frame: 22, end_frame: 158, athlete_key: 'T1' }, { start_frame: 20, end_frame: 160, athlete_key: 'T1' }, { start_frame: 172, end_frame: 198, athlete_key: 'T2' }] }] });
  E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pred.id });

  // Rendered output rendered by the same crop path the EDL describes (real ffmpeg, not mocked).
  mkdirSync(ctx.outputsDir, { recursive: true });
  const outFile = 'demo-output-001.mp4';
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', '-i', ctx.archive.pathFor(s1.archive_key), '-vf',
    "crop=w=360:h=640:x='clip(2*n-160+if(gte(n,150),90,0),0,iw-360)':y=40,scale=360:640", '-frames:v', '240', '-pix_fmt', 'yuv420p', '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8', '-b:v', '0', '-crf', '36', '-an', path.join(ctx.outputsDir, 'demo-output-001.webm')], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr);
  const edl = { schema: 'edl/v1', output_id: 'demo-output-001', run_id: 'demo-run-001', source_sha256: s1.sha256, source: { width: 1280, height: 720 },
    output: { width: 360, height: 640, fps: 30 }, mode: 'tracked_crop', rotation: 0, output_file: 'demo-output-001.webm',
    shots: [
      { out_start: 0, out_end: 80, src_start: 0, speed: 1, crop_start: { cx: 180, cy: 360, w: 360, h: 640 } },
      { out_start: 80, out_end: 150, src_start: 80, speed: 1, crop_start: { cx: 180, cy: 360, w: 360, h: 640 }, crop_end: { cx: 318, cy: 360, w: 360, h: 640 } },
      { out_start: 150, out_end: 240, src_start: 150, speed: 1, crop_start: { cx: 410, cy: 360, w: 360, h: 640 }, crop_end: { cx: 588, cy: 360, w: 360, h: 640 } }] };
  const stored = L.storeEdl(db, edl, s1.id);
  if (!quiet) console.log('seeded', { home, sources: db.prepare('select count(*) n from sources').get().n, edl: stored.id });
  return { ctx, s1, s2, ds, pred, edl: stored };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const home = path.resolve(process.argv[2] ?? '.demo-home');
  await seed(home);
  console.log(`run:  STUDIO_HOME=${home} STUDIO_TOKEN=demo-token node server/main.mjs\nopen: http://127.0.0.1:4173/?t=demo-token`);
}
