// Deterministic blind evaluation: frozen dataset vs imported pipeline predictions.
// Pure function core (`evaluateSource`) + thin persistence. No wall-clock or randomness in the report.
import { randomUUID } from 'node:crypto';
import { now, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { digestOf } from './annotations.mjs';

export const EVALUATOR_VERSION = 'eval-1.3.0';
// Addendum §8: ranking = IoU desc, then combined |Δstart|+|Δend| asc, then truth id, then prediction index.
export const MATCHING_VERSION = 'match-2';
export const METRIC_TOLERANCE_VERSION = 'tol-2';
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

/** Deterministic one-to-one GT/prediction pairing (shared by the evaluator and the error review). */
export function matchEvents(gt, preds, params) {
  const thr = params.iou_threshold;
  const G = gt.segments.filter(s => s.decision === 'include').map(s => ({ ...s }))
    .sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame || cmp(a.id, b.id));
  const P = preds.map((p, i) => ({ ...p, idx: i }))
    .sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame || a.idx - b.idx);
  const pairs = [];
  // No cross-sport matching: a prediction that declares a sport only pairs with GT of that same sport.
  // (Predictions that declare none — legacy exports — pair by time/IoU alone and are counted under the sport of what they matched.)
  for (const g of G) for (const p of P) { if (p.sport_id != null && p.sport_id !== gSport(g)) continue; const v = iou1d(g, p); if (v >= thr) pairs.push({ g, p, iou: v }); }
  const bErr = q => Math.abs(q.g.start_frame - q.p.start_frame) + Math.abs(q.g.end_frame - q.p.end_frame);
  pairs.sort((x, y) => y.iou - x.iou || bErr(x) - bErr(y) || cmp(x.g.id, y.g.id) || x.p.idx - y.p.idx);
  const usedG = new Set(), usedP = new Set(), matches = [];
  for (const m of pairs) {
    if (usedG.has(m.g.id) || usedP.has(m.p.idx)) continue;
    usedG.add(m.g.id); usedP.add(m.p.idx); matches.push(m);
  }
  return { thr, G, P, matches, usedG, usedP };
}
const gSport = g => g.resolved_sport_id ?? 'unknown';

/** @returns per-source result with every decision traceable to a reason code. */
export function evaluateSource(gt, preds, params, rejected = []) {
  const { thr, G, P, matches, usedG, usedP } = matchEvents(gt, preds, params);
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
  let missedButRejected = 0;
  for (const g of G) if (!usedG.has(g.id)) {
    // Diagnosis only: was the event found by the pipeline and then rejected (selection problem) or never found (detection problem)?
    const rj = rejected.find(r => overlaps(g, r));
    if (rj) missedButRejected++;
    errors.push({ type: 'missed_event', segment_id: g.id, start_frame: g.start_frame, end_frame: g.end_frame, ...(rj ? { pipeline_rejected: rj.reason } : {}) });
  }
  errors.sort((a, b) => a.start_frame - b.start_frame || cmp(a.type, b.type));
  // Per-sport denominators (a prediction is attributed to its declared sport, else to the sport of the GT it matched, else 'unspecified').
  const bySport = {};
  const bs = k => bySport[k] ??= { gt_included: 0, predictions: 0, matched: 0, missed: 0, false_positives: 0, duplicates: 0, predicted_excluded: 0 };
  for (const g of G) { const b = bs(gSport(g)); b.gt_included++; if (usedG.has(g.id)) b.matched++; else b.missed++; }
  // Sport-specific context — ONLY from what humans annotated (never inferred from pixels; spec §18):
  //   surfing: a 'complete' wave has annotated takeoff AND landing and no missing_takeoff/missing_landing reason;
  //   other sports: events whose required context attributes (attrs) were annotated.
  for (const g of G) {
    const b = bs(gSport(g)), sport = gSport(g);
    if (sport === 'surfing') {
      const complete = g.key_moments?.takeoff_frame != null && g.key_moments?.landing_frame != null && !(g.reason_codes ?? []).some(r => r === 'missing_takeoff' || r === 'missing_landing');
      b.complete_wave_annotated = (b.complete_wave_annotated ?? 0) + (complete ? 1 : 0);
      b.complete_wave_matched = (b.complete_wave_matched ?? 0) + (complete && usedG.has(g.id) ? 1 : 0);
    } else if (sport !== 'unknown') {
      const ctx = g.attrs && Object.values(g.attrs).some(v => v != null && v !== '');
      b.context_annotated = (b.context_annotated ?? 0) + (ctx ? 1 : 0);
      b.context_matched = (b.context_matched ?? 0) + (ctx && usedG.has(g.id) ? 1 : 0);
    }
  }
  const matchedSportOf = new Map(matches.map(m => [m.p.idx, gSport(m.g)]));
  const typeOf = new Map(errors.filter(e => e.pred_index != null).map(e => [e.pred_index, e.type]));
  for (const p of P) {
    const b = bs(p.sport_id ?? matchedSportOf.get(p.idx) ?? 'unspecified'); b.predictions++;
    const t = typeOf.get(p.idx);
    if (t === 'false_positive') b.false_positives++; else if (t === 'duplicate') b.duplicates++; else if (t === 'predicted_excluded') b.predicted_excluded++;
  }
  return {
    gt_included: G.length, predictions: P.length, matched: matches.length, missed: G.length - matches.length,
    ...counts, missed_but_rejected: missedButRejected, attributable, correct_attribution: correctAttr,
    sum_abs_start_error: startErr, sum_abs_end_error: endErr, uncertain_gt: uncertain.length, by_sport: bySport, errors,
  };
}


/** Identity keys are pipeline-global. Per-video relabeling would conceal false merges and splits. */
export function summarizeGlobalIdentity(pairs) {
  const byPred = new Map(), byTruth = new Map(), joint = new Map();
  for (const row of pairs) {
    const key = String(row.predicted_athlete_key), ath = String(row.gt_athlete_id);
    if (!byPred.has(key)) byPred.set(key, new Map());
    if (!byTruth.has(ath)) byTruth.set(ath, new Map());
    byPred.get(key).set(ath, (byPred.get(key).get(ath) ?? 0) + 1);
    byTruth.get(ath).set(key, (byTruth.get(ath).get(key) ?? 0) + 1);
    const pairKey = JSON.stringify([key, ath]);
    joint.set(pairKey, (joint.get(pairKey) ?? 0) + 1);
  }
  const n = pairs.length;
  let precision = 0, recall = 0;
  const predTotals = new Map([...byPred].map(([k, v]) => [k, [...v.values()].reduce((a, b) => a + b, 0)]));
  const gtTotals = new Map([...byTruth].map(([k, v]) => [k, [...v.values()].reduce((a, b) => a + b, 0)]));
  for (const row of pairs) {
    const key = String(row.predicted_athlete_key), ath = String(row.gt_athlete_id);
    const together = joint.get(JSON.stringify([key, ath]));
    precision += together / predTotals.get(key);
    recall += together / gtTotals.get(ath);
  }
  const rounded = n => Math.round(n * 1e6) / 1e6;
  const bcubedPrecision = n ? rounded(precision / n) : null;
  const bcubedRecall = n ? rounded(recall / n) : null;
  const bcubedF1 = n && precision + recall ? rounded(2 * precision * recall / (n * (precision + recall))) : null;

  // Establish one deterministic global attribution for diagnostics, never a different
  // prediction->truth relabeling in every video.
  const assignments = [...joint].map(([encoded, count]) => {
    const [key, ath] = JSON.parse(encoded);
    return { key, ath, count };
  }).sort((a, b) => b.count - a.count || cmp(a.key, b.key) || cmp(a.ath, b.ath));
  const mappedKeys = new Set(), mappedAthletes = new Set(), predictedToTruth = new Map();
  let correct = 0;
  for (const { key, ath, count } of assignments) {
    if (mappedKeys.has(key) || mappedAthletes.has(ath)) continue;
    mappedKeys.add(key); mappedAthletes.add(ath);
    predictedToTruth.set(key, ath);
    correct += count;
  }
  const falseMerges = [...byPred].filter(([, truths]) => truths.size > 1).map(([key, truths]) => ({
    predicted_athlete_key: key, gt_athlete_ids: [...truths.keys()].sort(cmp),
  }));
  const falseSplits = [...byTruth].filter(([, preds]) => preds.size > 1).map(([ath, preds]) => ({
    gt_athlete_id: ath, predicted_athlete_keys: [...preds.keys()].sort(cmp),
  }));
  return {
    matched_events_with_identity: n,
    correct_global_attribution: correct,
    bcubed_precision: bcubedPrecision,
    bcubed_recall: bcubedRecall,
    bcubed_f1: bcubedF1,
    false_merge_clusters: falseMerges.length,
    false_split_athletes: falseSplits.length,
    false_merges: falseMerges,
    false_splits: falseSplits,
    attribution_errors: pairs.filter(row =>
      predictedToTruth.get(String(row.predicted_athlete_key)) !== String(row.gt_athlete_id)
    ).map(row => ({ source_sha256: row.source_sha256, segment_id: row.segment_id,
      pred_index: row.pred_index, reason_code: 'wrong_athlete_global',
      predicted_athlete_key: row.predicted_athlete_key, gt_athlete_id: row.gt_athlete_id })),
  };
}

const ratio = (n, d) => d > 0 ? Math.round(n / d * 1e6) / 1e6 : null;

export function importPredictions(db, { run_id, pipeline_version, sources, extra = {} }) {
  if (!run_id || !pipeline_version || !Array.isArray(sources)) throw new ApiError('INVALID_INPUT');
  const sourceDigests = new Set();
  for (const s of sources) {
    if (!/^[0-9a-f]{64}$/.test(s.source_sha256 ?? '') || !Array.isArray(s.events)) throw new ApiError('INVALID_INPUT');
    if (sourceDigests.has(s.source_sha256)) throw new ApiError('INVALID_INPUT', 'duplicate source_sha256 in prediction manifest');
    sourceDigests.add(s.source_sha256);
    for (const e of s.events) if (!Number.isInteger(e.start_frame) || !Number.isInteger(e.end_frame) || e.end_frame <= e.start_frame) throw new ApiError('INVALID_INTERVAL');
  }
  const payload = { run_id, pipeline_version, sources, ...extra };
  const id = randomUUID();
  db.prepare('insert into pipeline_predictions(id,run_id,pipeline_version,payload,digest,created_at) values(?,?,?,?,?,?)')
    .run(id, run_id, pipeline_version, JSON.stringify(payload), digestOf(payload), now());
  return { id };
}

export function runEvaluation(db, { dataset_id, prediction_id, params = {} }) {
  const p = { ...DEFAULT_PARAMS, ...params };
  // The evaluator reads frozen ground truth ONLY through these views (its DB role has no other access).
  const ds = db.prepare('select * from frozen_datasets where id=?').get(dataset_id);
  const pr = db.prepare('select * from pipeline_predictions where id=?').get(prediction_id);
  if (!ds || !pr) throw new ApiError('NOT_FOUND');
  // §8.3: a missing/invalid matching configuration is INCONCLUSIVE, never a success.
  if (!(typeof p.iou_threshold === 'number' && p.iou_threshold > 0 && p.iou_threshold <= 1) || !Array.isArray(p.splits) || !p.splits.length) {
    throw new ApiError('INVALID_INPUT', 'inconclusive: invalid event matching configuration');
  }
  // §10: the complete comparison identity; retries with the same tuple resolve to the same evaluation run.
  const identity = { dataset_version_id: dataset_id, dataset_manifest_sha256: ds.digest, pipeline_run_id: pr.run_id, prediction_manifest_sha256: pr.digest,
    evaluator_version: EVALUATOR_VERSION, evaluator_config_sha256: digestOf(p), event_matching_config_version: MATCHING_VERSION, metric_tolerance_version: METRIC_TOLERANCE_VERSION };
  const identityKey = digestOf(identity);
  const prior = db.prepare('select * from evaluation_runs where identity_key=?').get(identityKey);
  if (prior) return { id: prior.id, digest: prior.digest, report: JSON.parse(prior.report), idempotent_replay: true };
  const predSources = JSON.parse(pr.payload).sources;
  const preds = new Map();
  const rejects = new Map();
  for (const s of predSources) {
    if (preds.has(s.source_sha256)) throw new ApiError('INVALID_INPUT', 'duplicate source_sha256 in stored prediction manifest');
    preds.set(s.source_sha256, s.events);
    rejects.set(s.source_sha256, s.rejected ?? []);
  }
  const per = [], bySportTot = {}, identityPairs = [];
  const tot = { gt_included: 0, predictions: 0, matched: 0, missed: 0, duplicates: 0, predicted_excluded: 0, false_positives: 0,
    unreviewed_predictions: 0, uncertain_overlap: 0, missed_but_rejected: 0, attributable: 0, correct_attribution: 0, sum_abs_start_error: 0, sum_abs_end_error: 0 };
  const members = db.prepare('select * from frozen_revisions where dataset_id=? order by sha256').all(dataset_id).filter(m => p.splits.includes(m.split));
  const missingPredictionSources = members.filter(m => !preds.has(m.sha256)).map(m => m.sha256);
  for (const m of members) {
    const gt = JSON.parse(m.content);
    const events = preds.get(m.sha256);
    const r = evaluateSource(gt, events ?? [], p, rejects.get(m.sha256) ?? []);
    for (const hit of matchEvents(gt, events ?? [], p).matches) {
      if (hit.g.athlete_id != null && hit.p.athlete_key != null) identityPairs.push({
        source_sha256: m.sha256, segment_id: hit.g.id, pred_index: hit.p.idx,
        predicted_athlete_key: String(hit.p.athlete_key), gt_athlete_id: String(hit.g.athlete_id),
      });
    }
    per.push({ sha256: m.sha256, split: m.split, revision_id: m.revision_id, has_prediction: !!events, identity_scope: 'source_local_diagnostic', ...r });
    for (const k of Object.keys(tot)) tot[k] += r[k];
    for (const [sp, c] of Object.entries(r.by_sport)) { const t = bySportTot[sp] ??= {}; for (const [k, v] of Object.entries(c)) t[k] = (t[k] ?? 0) + v; }
  }
  const identityResult = summarizeGlobalIdentity(identityPairs);
  tot.correct_attribution = identityResult.correct_global_attribution;
  const report = {
    status: missingPredictionSources.length || !members.length ? 'inconclusive' : 'complete',
    evidence_gaps: { expected_source_count: members.length, matched_source_count: members.length - missingPredictionSources.length,
      missing_prediction_sources: missingPredictionSources,
      reason_codes: [...(!members.length ? ['no_ground_truth_in_selected_splits'] : []),
        ...(missingPredictionSources.length ? ['missing_source_prediction_manifest'] : [])] },
    identity: identityResult,
    evaluator_version: EVALUATOR_VERSION, matching_version: MATCHING_VERSION, comparison_identity: identity, params: p, dataset_digest: ds.digest, prediction_digest: pr.digest,
    pipeline_version: pr.pipeline_version, run_id: pr.run_id, totals: tot,
    metrics: {
      event_recall: ratio(tot.matched, tot.gt_included),
      event_precision: ratio(tot.matched, tot.matched + tot.false_positives + tot.duplicates + tot.predicted_excluded),
      identity_accuracy: ratio(tot.correct_attribution, tot.attributable),
      identity_bcubed_precision: identityResult.bcubed_precision,
      identity_bcubed_recall: identityResult.bcubed_recall,
      identity_bcubed_f1: identityResult.bcubed_f1,
      identity_evidence_coverage: ratio(identityPairs.length, tot.gt_included),
      mean_abs_start_error_frames: ratio(tot.sum_abs_start_error, tot.matched),
      mean_abs_end_error_frames: ratio(tot.sum_abs_end_error, tot.matched),
      unreviewed_prediction_share: ratio(tot.unreviewed_predictions, tot.predictions),
    },
    by_sport: Object.fromEntries(Object.keys(bySportTot).sort().map(sp => { const t = bySportTot[sp]; return [sp, { ...t, event_recall: ratio(t.matched, t.gt_included),
      event_precision: ratio(t.matched, t.matched + t.false_positives + t.duplicates + t.predicted_excluded),
      ...(t.complete_wave_annotated != null ? { complete_wave_recall: ratio(t.complete_wave_matched, t.complete_wave_annotated) } : {}),
      ...(t.context_annotated != null ? { annotated_context_recall: ratio(t.context_matched, t.context_annotated) } : {}) }]; })),
    sport_policy: 'no cross-sport matching; totals/metrics above are pooled counts — use by_sport for per-sport denominators',
    per_source: per,
  };
  const digest = digestOf(report);
  const id = randomUUID();
  db.prepare('insert into evaluation_runs(id,dataset_id,prediction_id,evaluator_version,params,report,digest,created_at,identity_key,matching_version) values(?,?,?,?,?,?,?,?,?,?)')
    .run(id, dataset_id, prediction_id, EVALUATOR_VERSION, JSON.stringify(p), JSON.stringify(report), digest, now(), identityKey, MATCHING_VERSION);
  audit(db, 'operator', 'evaluation_run', id, { digest });
  return { id, digest, report };
}

export function listEvaluations(db) {
  return db.prepare('select e.id,e.created_at,e.digest,e.report,d.name dataset_name from evaluation_runs e join frozen_datasets d on d.id=e.dataset_id order by e.created_at desc').all()
    .map(e => { const r = JSON.parse(e.report); return { id: e.id, created_at: e.created_at, digest: e.digest, dataset_name: e.dataset_name,
      pipeline_version: r.pipeline_version, run_id: r.run_id, metrics: r.metrics, totals: r.totals }; });
}
