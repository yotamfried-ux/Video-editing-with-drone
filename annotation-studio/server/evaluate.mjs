// Deterministic blind evaluation: frozen dataset vs imported pipeline predictions.
// Pure function core (`evaluateSource`) + thin persistence. No wall-clock or randomness in the report.
import { randomUUID } from 'node:crypto';
import { now, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { digestOf } from './annotations.mjs';

export const EVALUATOR_VERSION = 'eval-1.0.0';
export const DEFAULT_PARAMS = { iou_threshold: 0.5, splits: ['test'] };

const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;

export function iou1d(a, b) {
  const lo = Math.max(a.start_frame, b.start_frame), hi = Math.min(a.end_frame, b.end_frame);
  const i = Math.max(0, hi - lo);
  const u = (a.end_frame - a.start_frame) + (b.end_frame - b.start_frame) - i;
  return u > 0 ? i / u : 0;
}
const overlaps = (a, b) => Math.min(a.end_frame, b.end_frame) > Math.max(a.start_frame, b.start_frame);
const inRanges = (frame, ranges) => ranges.some(r => frame >= r.start_frame && frame < r.end_frame);

/** @returns per-source result with every decision traceable to a reason code. */
export function evaluateSource(gt, preds, params) {
  const thr = params.iou_threshold;
  const G = gt.segments.filter(s => s.decision === 'include').map(s => ({ ...s }))
    .sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame || cmp(a.id, b.id));
  const P = preds.map((p, i) => ({ ...p, idx: i }))
    .sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame || a.idx - b.idx);
  const pairs = [];
  for (const g of G) for (const p of P) { const v = iou1d(g, p); if (v >= thr) pairs.push({ g, p, iou: v }); }
  pairs.sort((x, y) => y.iou - x.iou || x.g.start_frame - y.g.start_frame || cmp(x.g.id, y.g.id) || x.p.idx - y.p.idx);
  const usedG = new Set(), usedP = new Set(), matches = [];
  for (const m of pairs) {
    if (usedG.has(m.g.id) || usedP.has(m.p.idx)) continue;
    usedG.add(m.g.id); usedP.add(m.p.idx); matches.push(m);
  }
  // Athlete attribution: pipeline athlete keys are arbitrary, so derive a deterministic
  // key->athlete mapping from co-occurrence over matched pairs, then flag deviations.
  const co = new Map();
  for (const m of matches) if (m.g.athlete_id && m.p.athlete_key != null) {
    const k = `${m.p.athlete_key}\u0000${m.g.athlete_id}`; co.set(k, (co.get(k) ?? 0) + 1);
  }
  const ranked = [...co.entries()].map(([k, n]) => ({ k, n, key: k.split('\u0000')[0], ath: k.split('\u0000')[1] }))
    .sort((a, b) => b.n - a.n || cmp(a.k, b.k));
  const keyToAth = new Map(), athUsed = new Set();
  for (const r of ranked) if (!keyToAth.has(r.key) && !athUsed.has(r.ath)) { keyToAth.set(r.key, r.ath); athUsed.add(r.ath); }
  const errors = [];
  let attributable = 0, correctAttr = 0, startErr = 0, endErr = 0;
  for (const m of matches) {
    startErr += Math.abs(m.g.start_frame - m.p.start_frame); endErr += Math.abs(m.g.end_frame - m.p.end_frame);
    if (m.g.athlete_id && m.p.athlete_key != null) {
      attributable++;
      if (keyToAth.get(String(m.p.athlete_key)) === m.g.athlete_id) correctAttr++;
      else errors.push({ type: 'wrong_athlete', segment_id: m.g.id, pred_index: m.p.idx, start_frame: m.g.start_frame, end_frame: m.g.end_frame });
    }
  }
  const matchedSegs = G.filter(g => usedG.has(g.id)).concat([]);
  const excluded = gt.segments.filter(s => s.decision === 'exclude');
  const uncertain = gt.segments.filter(s => s.decision === 'uncertain');
  const counts = { duplicates: 0, predicted_excluded: 0, false_positives: 0, unreviewed_predictions: 0, uncertain_overlap: 0 };
  for (const p of P) {
    if (usedP.has(p.idx)) continue;
    const dupOf = matchedSegs.find(g => iou1d(g, p) >= thr);
    if (dupOf) { counts.duplicates++; errors.push({ type: 'duplicate', segment_id: dupOf.id, pred_index: p.idx, start_frame: p.start_frame, end_frame: p.end_frame }); continue; }
    if (excluded.some(s => overlaps(s, p))) { counts.predicted_excluded++; errors.push({ type: 'predicted_excluded', pred_index: p.idx, start_frame: p.start_frame, end_frame: p.end_frame }); continue; }
    if (uncertain.some(s => overlaps(s, p))) { counts.uncertain_overlap++; continue; }
    const mid = Math.floor((p.start_frame + p.end_frame) / 2);
    if (!inRanges(mid, gt.reviewed_ranges)) { counts.unreviewed_predictions++; continue; }
    counts.false_positives++; errors.push({ type: 'false_positive', pred_index: p.idx, start_frame: p.start_frame, end_frame: p.end_frame });
  }
  for (const g of G) if (!usedG.has(g.id)) errors.push({ type: 'missed_event', segment_id: g.id, start_frame: g.start_frame, end_frame: g.end_frame });
  errors.sort((a, b) => a.start_frame - b.start_frame || cmp(a.type, b.type));
  return {
    gt_included: G.length, predictions: P.length, matched: matches.length, missed: G.length - matches.length,
    ...counts, attributable, correct_attribution: correctAttr,
    sum_abs_start_error: startErr, sum_abs_end_error: endErr, uncertain_gt: uncertain.length, errors,
  };
}

const ratio = (n, d) => d > 0 ? Math.round(n / d * 1e6) / 1e6 : null;

export function importPredictions(db, { run_id, pipeline_version, sources }) {
  if (!run_id || !pipeline_version || !Array.isArray(sources)) throw new ApiError('INVALID_INPUT');
  for (const s of sources) {
    if (!/^[0-9a-f]{64}$/.test(s.source_sha256 ?? '') || !Array.isArray(s.events)) throw new ApiError('INVALID_INPUT');
    for (const e of s.events) if (!Number.isInteger(e.start_frame) || !Number.isInteger(e.end_frame) || e.end_frame <= e.start_frame) throw new ApiError('INVALID_INTERVAL');
  }
  const payload = { run_id, pipeline_version, sources };
  const id = randomUUID();
  db.prepare('insert into pipeline_predictions(id,run_id,pipeline_version,payload,digest,created_at) values(?,?,?,?,?,?)')
    .run(id, run_id, pipeline_version, JSON.stringify(payload), digestOf(payload), now());
  return { id };
}

export function runEvaluation(db, { dataset_id, prediction_id, params = {} }) {
  const p = { ...DEFAULT_PARAMS, ...params };
  const ds = db.prepare('select * from dataset_versions where id=?').get(dataset_id);
  const pr = db.prepare('select * from pipeline_predictions where id=?').get(prediction_id);
  if (!ds || !pr) throw new ApiError('NOT_FOUND');
  const preds = new Map(JSON.parse(pr.payload).sources.map(s => [s.source_sha256, s.events]));
  const per = [];
  const tot = { gt_included: 0, predictions: 0, matched: 0, missed: 0, duplicates: 0, predicted_excluded: 0, false_positives: 0,
    unreviewed_predictions: 0, uncertain_overlap: 0, attributable: 0, correct_attribution: 0, sum_abs_start_error: 0, sum_abs_end_error: 0 };
  const members = db.prepare('select * from dataset_members where dataset_id=? order by sha256').all(dataset_id).filter(m => p.splits.includes(m.split));
  for (const m of members) {
    const rev = db.prepare('select content from annotation_revisions where id=?').get(m.revision_id);
    const gt = JSON.parse(rev.content);
    const events = preds.get(m.sha256);
    const r = evaluateSource(gt, events ?? [], p);
    per.push({ sha256: m.sha256, split: m.split, revision_id: m.revision_id, has_prediction: !!events, ...r });
    for (const k of Object.keys(tot)) tot[k] += r[k];
  }
  const report = {
    evaluator_version: EVALUATOR_VERSION, params: p, dataset_digest: ds.digest, prediction_digest: pr.digest,
    pipeline_version: pr.pipeline_version, run_id: pr.run_id, totals: tot,
    metrics: {
      event_recall: ratio(tot.matched, tot.gt_included),
      event_precision: ratio(tot.matched, tot.matched + tot.false_positives + tot.duplicates + tot.predicted_excluded),
      identity_accuracy: ratio(tot.correct_attribution, tot.attributable),
      mean_abs_start_error_frames: ratio(tot.sum_abs_start_error, tot.matched),
      mean_abs_end_error_frames: ratio(tot.sum_abs_end_error, tot.matched),
      unreviewed_prediction_share: ratio(tot.unreviewed_predictions, tot.predictions),
    },
    per_source: per,
  };
  const digest = digestOf(report);
  const id = randomUUID();
  db.prepare('insert into evaluation_runs(id,dataset_id,prediction_id,evaluator_version,params,report,digest,created_at) values(?,?,?,?,?,?,?,?)')
    .run(id, dataset_id, prediction_id, EVALUATOR_VERSION, JSON.stringify(p), JSON.stringify(report), digest, now());
  audit(db, 'operator', 'evaluation_run', id, { digest });
  return { id, digest, report };
}

export function listEvaluations(db) {
  return db.prepare('select e.id,e.created_at,e.digest,e.report,d.name dataset_name from evaluation_runs e join dataset_versions d on d.id=e.dataset_id order by e.created_at desc').all()
    .map(e => { const r = JSON.parse(e.report); return { id: e.id, created_at: e.created_at, digest: e.digest, dataset_name: e.dataset_name,
      pipeline_version: r.pipeline_version, run_id: r.run_id, metrics: r.metrics, totals: r.totals }; });
}
