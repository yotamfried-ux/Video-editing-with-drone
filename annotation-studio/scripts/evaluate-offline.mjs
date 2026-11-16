#!/usr/bin/env node
// Offline, read-only GT evaluation of one pipeline run (RC-08): the studio's own evaluator, on files.
//
//   node scripts/evaluate-offline.mjs --dataset frozen-dataset.json --predictions predictions.v1.json --out eval.json
//
// frozen-dataset.json: { "dataset_id", "digest", "members": [{ "sha256", "split", "revision_id", "content" }] } -
// an export of frozen_datasets + frozen_revisions (content = the frozen GT revision, object or JSON string).
// predictions.v1.json: the pipeline's export (scripts/export_pipeline_predictions.py).
//
// Nothing is written to any database; the frozen GT is only read. Inference never sees this file: the evaluator
// runs after the pipeline, on its exported predictions. A run whose predictions miss a frozen source, or whose
// configuration is invalid, is reported `inconclusive`, never as a success.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { buildEvaluationReport, DEFAULT_PARAMS, EVALUATOR_VERSION, MATCHING_VERSION, METRIC_TOLERANCE_VERSION } from '../server/evaluate.mjs';
import { convertPredictionsV1 } from '../server/imports.mjs';

const canonical = v => JSON.stringify(v, (k, x) => (x && typeof x === 'object' && !Array.isArray(x)
  ? Object.fromEntries(Object.keys(x).sort().map(key => [key, x[key]])) : x));
const sha = v => createHash('sha256').update(canonical(v)).digest('hex');

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  if (i < 0 || !process.argv[i + 1]) { console.error(`missing --${name}`); process.exit(2); }
  return process.argv[i + 1];
}

/**
 * Physical rides vs manoeuvres: GT-v1 often splits one ride into contiguous segments of the same athlete (one per
 * manoeuvre). Segment-level IoU then counts a prediction covering the whole ride as several misses. Here contiguous
 * (gap <= RIDE_GAP_FRAMES) include segments of one athlete form one physical ride; a ride is covered when selected
 * predictions cover >= RIDE_MIN_COVERAGE of its frames. Selected frames inside an excluded GT segment are contamination.
 */
export const RIDE_GAP_FRAMES = 3;
export const RIDE_MIN_COVERAGE = 0.5;
export function physicalRides(gt, selected) {
  const inc = (gt.segments ?? []).filter(s => s.decision === 'include')
    .sort((a, b) => a.start_frame - b.start_frame);
  const rides = [];
  for (const s of inc) {
    const last = rides[rides.length - 1];
    if (last && last.athlete_id === s.athlete_id && s.start_frame - last.end_frame <= RIDE_GAP_FRAMES) {
      last.end_frame = Math.max(last.end_frame, s.end_frame); last.segment_ids.push(s.id);
    } else rides.push({ athlete_id: s.athlete_id, start_frame: s.start_frame, end_frame: s.end_frame, segment_ids: [s.id] });
  }
  const covered = (a, b) => {
    let n = 0;
    for (let f = a; f < b; f++) if (selected.some(p => f >= p.start_frame && f < p.end_frame)) n++;
    return n;
  };
  for (const r of rides) {
    r.coverage = Math.round(covered(r.start_frame, r.end_frame) / Math.max(1, r.end_frame - r.start_frame) * 1e4) / 1e4;
    r.covered = r.coverage >= RIDE_MIN_COVERAGE;
  }
  const excluded = (gt.segments ?? []).filter(s => s.decision === 'exclude');
  const contamination = excluded.map(x => ({ segment_id: x.id, selected_frames: covered(x.start_frame, x.end_frame),
    frames: x.end_frame - x.start_frame })).filter(x => x.selected_frames > 0);
  return { rides, contamination };
}

export function evaluateOffline(dataset, v1, params = {}) {
  if (!dataset || !Array.isArray(dataset.members) || !dataset.dataset_id) throw new Error('invalid frozen dataset export');
  if (v1?.schema !== 'predictions/v1') throw new Error('predictions/v1 expected');
  for (const k of ['run_id', 'pipeline_commit']) if (!v1[k] || v1[k] === 'unknown') throw new Error(`traceability: ${k} is required`);
  const p = { ...DEFAULT_PARAMS, ...params };
  const members = dataset.members
    .map(m => ({ ...m, content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content) }))
    .filter(m => p.splits.includes(m.split))
    .sort((a, b) => (a.sha256 < b.sha256 ? -1 : a.sha256 > b.sha256 ? 1 : 0));
  const fpsBySha = new Map(dataset.members.map(m => {
    const c = typeof m.content === 'string' ? JSON.parse(m.content) : m.content;
    return [m.sha256, c?.fps_num && c?.fps_den ? { fps_num: c.fps_num, fps_den: c.fps_den } : null];
  }));
  const { sources, unmatched } = convertPredictionsV1(v1, s => fpsBySha.get(s) ?? null);
  const payload = { run_id: v1.run_id, pipeline_version: String(v1.pipeline_commit).slice(0, 12), sources };
  const pr = { run_id: v1.run_id, pipeline_version: payload.pipeline_version, payload: JSON.stringify(payload),
    digest: sha({ ...payload, export_digest: v1.digest }) };
  const ds = { id: dataset.dataset_id, digest: dataset.digest ?? sha(dataset.members) };
  const identity = { dataset_version_id: ds.id, dataset_manifest_sha256: ds.digest, pipeline_run_id: pr.run_id,
    prediction_manifest_sha256: pr.digest, evaluator_version: EVALUATOR_VERSION, evaluator_config_sha256: sha(p),
    event_matching_config_version: MATCHING_VERSION, metric_tolerance_version: METRIC_TOLERANCE_VERSION };
  const report = buildEvaluationReport({ ds, pr, members, params: p, identity });
  const bySha = new Map(sources.map(x => [x.source_sha256, x.events]));
  const physical = members.map(m => ({ sha256: m.sha256, ...physicalRides(JSON.parse(m.content), bySha.get(m.sha256) ?? []) }));
  const rides = physical.flatMap(x => x.rides);
  const physical_summary = { ride_count: rides.length, covered: rides.filter(r => r.covered).length,
    ride_recall: rides.length ? Math.round(rides.filter(r => r.covered).length / rides.length * 1e6) / 1e6 : null,
    contaminated_excluded_segments: physical.reduce((n, x) => n + x.contamination.length, 0),
    gap_frames: RIDE_GAP_FRAMES, min_coverage: RIDE_MIN_COVERAGE };
  const full = { ...report, physical_rides: { summary: physical_summary, per_source: physical } };
  return { ...full, mode: 'offline_read_only', unmatched_prediction_sources: unmatched, report_digest: sha(full) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const dataset = JSON.parse(readFileSync(arg('dataset'), 'utf8'));
  const v1 = JSON.parse(readFileSync(arg('predictions'), 'utf8'));
  const out = evaluateOffline(dataset, v1);
  writeFileSync(arg('out'), JSON.stringify(out, null, 2));
  console.log(`evaluation ${out.status}: recall=${out.metrics.event_recall} precision=${out.metrics.event_precision} ` +
    `identity_accuracy=${out.metrics.identity_accuracy} (digest ${out.report_digest.slice(0, 12)})`);
}
