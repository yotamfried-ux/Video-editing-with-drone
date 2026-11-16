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
  return { ...report, mode: 'offline_read_only', unmatched_prediction_sources: unmatched, report_digest: sha(report) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const dataset = JSON.parse(readFileSync(arg('dataset'), 'utf8'));
  const v1 = JSON.parse(readFileSync(arg('predictions'), 'utf8'));
  const out = evaluateOffline(dataset, v1);
  writeFileSync(arg('out'), JSON.stringify(out, null, 2));
  console.log(`evaluation ${out.status}: recall=${out.metrics.event_recall} precision=${out.metrics.event_precision} ` +
    `identity_accuracy=${out.metrics.identity_accuracy} (digest ${out.report_digest.slice(0, 12)})`);
}
