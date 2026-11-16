// Offline, read-only evaluation of a pipeline run against a frozen dataset export (RC-08).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync } from 'node:fs';
import { evaluateOffline } from '../scripts/evaluate-offline.mjs';

const A = 'a'.repeat(64), B = 'b'.repeat(64);
const gtA = { fps_num: 30, fps_den: 1, reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }], segments: [
  { id: 'gA1', start_frame: 0, end_frame: 300, decision: 'include', athlete_id: 'ath1' },
  { id: 'gA2', start_frame: 600, end_frame: 900, decision: 'include', athlete_id: 'ath2' },
  { id: 'gA3', start_frame: 1200, end_frame: 1500, decision: 'exclude' }] };
const gtB = { fps_num: 30, fps_den: 1, reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }], segments: [{ id: 'gB1', start_frame: 30, end_frame: 330, decision: 'include', athlete_id: 'ath1' }] };
const dataset = { dataset_id: 'ds-1', digest: 'd'.repeat(64), members: [
  { sha256: A, split: 'test', revision_id: 'r1', content: gtA },
  { sha256: B, split: 'test', revision_id: 'r2', content: JSON.stringify(gtB) }] };

const preds = (sources) => ({ schema: 'predictions/v1', run_id: 'run-1', pipeline_commit: 'abcdef1234567890', digest: 'p'.repeat(64), sources });
const ev = (s, e, key, decision = 'selected') => ({ start_frame: s, end_frame: e, athlete_key: key, decision, candidate_id: `${s}-${e}` });

test('offline evaluation is deterministic and complete when every frozen source has predictions', () => {
  const v1 = preds([
    { source_sha256: A, events: [ev(0, 300, 'k1'), ev(600, 900, 'k2'), ev(1200, 1500, 'k3')] },
    { source_sha256: B, events: [ev(30, 330, 'k1')] }]);
  const one = evaluateOffline(dataset, v1), two = evaluateOffline(dataset, v1);
  assert.equal(one.status, 'complete');
  assert.equal(one.report_digest, two.report_digest);
  assert.equal(one.mode, 'offline_read_only');
  assert.equal(one.totals.matched, 3);
  assert.equal(one.totals.predicted_excluded, 1, 'a prediction inside an excluded GT window is counted against precision');
  assert.equal(one.metrics.event_recall, 1);
});

test('a missed valid action and a false inclusion are both reported', () => {
  const v1 = preds([
    { source_sha256: A, events: [ev(0, 300, 'k1'), ev(2000, 2300, 'k9'), ev(600, 900, 'k2', 'rejected')] },
    { source_sha256: B, events: [ev(30, 330, 'k1')] }]);
  const r = evaluateOffline(dataset, v1);
  assert.equal(r.totals.missed, 1);
  assert.ok(r.totals.false_positives >= 1);
  assert.ok(r.metrics.event_recall < 1 && r.metrics.event_precision < 1);
});

test('a frozen source without predictions makes the evaluation inconclusive, never a success', () => {
  const r = evaluateOffline(dataset, preds([{ source_sha256: A, events: [ev(0, 300, 'k1')] }]));
  assert.equal(r.status, 'inconclusive');
  assert.deepEqual(r.evidence_gaps.missing_prediction_sources, [B]);
});

test('traceability is required and nothing is written to a database', () => {
  const before = readdirSync('.').sort().join();
  assert.throws(() => evaluateOffline(dataset, { ...preds([]), pipeline_commit: 'unknown' }), /traceability/);
  evaluateOffline(dataset, preds([{ source_sha256: A, events: [] }, { source_sha256: B, events: [] }]));
  assert.equal(readdirSync('.').sort().join(), before, 'the offline evaluator must not create files or databases');
  assert.ok(!existsSync('./data.db'));
});

test('contiguous manoeuvre segments of one athlete count as one physical ride; excluded frames are contamination', () => {
  const gt = { reviewed_ranges: [{ start_frame: 0, end_frame: 2000 }], segments: [
    { id: 's1', start_frame: 0, end_frame: 300, decision: 'include', athlete_id: 'a' },
    { id: 's2', start_frame: 300, end_frame: 700, decision: 'include', athlete_id: 'a' },
    { id: 's3', start_frame: 702, end_frame: 900, decision: 'include', athlete_id: 'a' },
    { id: 's4', start_frame: 900, end_frame: 1000, decision: 'include', athlete_id: 'b' },
    { id: 'x1', start_frame: 1500, end_frame: 1600, decision: 'exclude' }] };
  return import('../scripts/evaluate-offline.mjs').then(({ physicalRides }) => {
    const r = physicalRides(gt, [{ start_frame: 0, end_frame: 900 }, { start_frame: 1550, end_frame: 1700 }]);
    assert.equal(r.rides.length, 2, 'three contiguous segments of athlete a are one ride; athlete b is another');
    assert.deepEqual(r.rides.map(x => x.covered), [true, false]);
    assert.deepEqual(r.contamination.map(c => [c.segment_id, c.selected_frames]), [['x1', 50]]);
  });
});
