// Blind-run error review: every disagreement explained (selection / identity / assembly / trim / framing).
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';
import * as R from '../server/review.mjs';

const SHA1 = 'a'.repeat(64), SHA2 = 'b'.repeat(64);
const report = { run_id: 'run-x', pipeline_version: 'abc', params: { iou_threshold: 0.5, splits: ['test'] } };
const videos = { [SHA1]: { source_id: 's1', name: 'DJI_0001.MP4', fps: 30 }, [SHA2]: { source_id: 's2', name: 'DJI_0002.MP4', fps: 30 } };
const athletes = { A: 'Dana', B: 'Noa' };
const types = (rv, c) => rv.items.filter(i => i.category === c).map(i => i.type).sort();

test('selection: used-but-should-not vs missed (rejected / never detected / poor overlap)', () => {
  const gt = { segments: [
    seg('g1', 0, 300, { athlete_id: 'A' }), seg('g2', 600, 900, { athlete_id: 'A' }), seg('g3', 1200, 1500, { athlete_id: 'A' }),
    seg('g4', 1800, 2100, { athlete_id: 'A' }), seg('ex', 2400, 2700, { decision: 'exclude', reason_codes: ['wipeout'] }),
  ], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const ps = [{ source_sha256: SHA1, events: [
    { start_frame: 0, end_frame: 300, athlete_key: 'k1', outputs: [{ output_id: 'reel-1' }] },
    { start_frame: 2450, end_frame: 2650, athlete_key: 'k1', outputs: [{ output_id: 'reel-1' }] },   // excluded wipeout, rendered
    { start_frame: 2800, end_frame: 2900, athlete_key: 'k1' },                                        // nothing there
    { start_frame: 1800, end_frame: 1850, athlete_key: 'k1' },                                        // poor overlap with g4
  ], rejected: [{ start_frame: 610, end_frame: 890, reason: 'low_score' }] }];
  const rv = R.buildReview({ report, predSources: ps, members: [{ sha256: SHA1, split: 'test', content: gt, owner_athlete_id: 'A' }], videos, athletes });
  assert.deepEqual(types(rv, 'selection_wrong_use'), ['false_positive', 'used_excluded']);
  const ex = rv.items.find(i => i.type === 'used_excluded');
  assert.deepEqual(ex.outputs, ['reel-1']); assert.deepEqual(ex.gt_reason_codes, ['wipeout']); assert.match(ex.explain_he, /reel-1/);
  assert.deepEqual(types(rv, 'selection_missed'), ['missed_never_detected', 'missed_poor_overlap', 'missed_rejected']);
  assert.equal(rv.items.find(i => i.type === 'missed_rejected').pipeline_reason, 'low_score');
  assert.equal(rv.items.find(i => i.type === 'missed_never_detected').segment_id, 'g3');
  assert.equal(rv.items.find(i => i.type === 'missed_rejected').start_sec, 20, 'times are reported in source seconds');
  assert.equal(rv.summary.missed, 3); assert.equal(rv.summary.used_wrongly, 2); assert.equal(rv.summary.matched_without_issue, 1);
});

test('identity across the run: wrong surfer, split identity, merged identities, no identity', () => {
  const g = (id, s, a) => seg(id, s, s + 300, { athlete_id: a });
  const gt1 = { segments: [g('a1', 0, 'A'), g('a2', 600, 'A'), g('b1', 1200, 'B')], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const gt2 = { segments: [g('a3', 0, 'A'), g('b2', 600, 'B')], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const ev = (s, k) => ({ start_frame: s, end_frame: s + 300, athlete_key: k });
  const ps = [{ source_sha256: SHA1, events: [ev(0, 'p1'), ev(600, 'p1'), ev(1200, 'p1')] },     // B seen as p1 (=A): merged + wrong
              { source_sha256: SHA2, events: [ev(0, 'p9'), { start_frame: 600, end_frame: 900, athlete_key: null }] }]; // A seen as p9 too: split; B no identity
  const rv = R.buildReview({ report, predSources: ps, members: [
    { sha256: SHA1, split: 'test', content: gt1, owner_athlete_id: 'A' }, { sha256: SHA2, split: 'test', content: gt2, owner_athlete_id: 'B' }], videos, athletes });
  const t = types(rv, 'identity');
  assert.ok(t.includes('wrong_athlete')); assert.ok(t.includes('athletes_merged')); assert.ok(t.includes('athlete_split')); assert.ok(t.includes('no_identity'));
  const w = rv.items.find(i => i.type === 'wrong_athlete' && i.segment_id === 'b1');
  assert.equal(w.athlete.label, 'Noa'); assert.equal(w.pipeline_athlete_as.label, 'Dana');
  assert.equal(rv.identity_map.find(m => m.pipeline_athlete_key === 'p1').mapped_to.id, 'A');
});

test('assembly: mixed reel, surfer without reel, same wave in two reels, surfer spread over reels', () => {
  const gt = { segments: [seg('a1', 0, 300, { athlete_id: 'A' }), seg('b1', 600, 900, { athlete_id: 'B' }), seg('a2', 1200, 1500, { athlete_id: 'A' })],
    keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const gt2 = { segments: [seg('c1', 0, 300, { athlete_id: 'C' })], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const ps = [{ source_sha256: SHA1, events: [
    { start_frame: 0, end_frame: 300, athlete_key: 'p1', outputs: [{ output_id: 'reel-A' }] },
    { start_frame: 600, end_frame: 900, athlete_key: 'p2', outputs: [{ output_id: 'reel-A' }] },
    { start_frame: 1200, end_frame: 1500, athlete_key: 'p1', outputs: [{ output_id: 'reel-A' }, { output_id: 'reel-Z' }] },
  ] }, { source_sha256: SHA2, events: [{ start_frame: 0, end_frame: 300, athlete_key: 'p3' }] }];
  const rv = R.buildReview({ report, predSources: ps, members: [{ sha256: SHA1, split: 'test', content: gt, owner_athlete_id: 'A' }, { sha256: SHA2, split: 'test', content: gt2, owner_athlete_id: 'C' }], videos, athletes });
  const t = types(rv, 'assembly');
  assert.deepEqual(t, ['athlete_split_across_outputs', 'athlete_without_output', 'event_in_multiple_outputs', 'mixed_athletes_in_output', 'selected_not_rendered']);
  const mixed = rv.items.find(i => i.type === 'mixed_athletes_in_output');
  assert.equal(mixed.output_id, 'reel-A'); assert.deepEqual(mixed.athletes.map(a => a.id), ['A', 'B']);
  assert.equal(rv.items.find(i => i.type === 'athlete_without_output').athlete.id, 'C');
});

test('trim: cut takeoff / cut landing / late start / dead time are told apart', () => {
  const km = (t, l) => ({ key_moments: { takeoff_frame: t, landing_frame: l } });
  const gt = { segments: [
    seg('t1', 0, 300, { athlete_id: 'A', ...km(30, 270) }),       // starts after takeoff -> cut_takeoff
    seg('t2', 600, 900, { athlete_id: 'A', ...km(620, 880) }),    // ends before landing -> cut_landing
    seg('t3', 1200, 1500, { athlete_id: 'A' }),                   // starts 1s late, no key moments -> late_start
    seg('t4', 1800, 2100, { athlete_id: 'A' }),                   // 2s of dead time before -> early_start
  ], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 3000 }] };
  const ps = [{ source_sha256: SHA1, events: [
    { start_frame: 40, end_frame: 300, athlete_key: 'k' }, { start_frame: 600, end_frame: 860, athlete_key: 'k' },
    { start_frame: 1230, end_frame: 1500, athlete_key: 'k' }, { start_frame: 1740, end_frame: 2100, athlete_key: 'k' },
  ] }];
  const rv = R.buildReview({ report, predSources: ps, members: [{ sha256: SHA1, split: 'test', content: gt, owner_athlete_id: 'A' }], videos, athletes });
  assert.deepEqual(types(rv, 'trim'), ['cut_landing', 'cut_takeoff', 'early_start', 'late_start']);
  assert.equal(rv.items.find(i => i.type === 'cut_takeoff').segment_id, 't1');
  assert.equal(rv.summary.matched, 4); assert.equal(rv.summary.matched_without_issue, 0);
});

test('framing: surfer out of the crop and off-centre become episodes on the output timeline', () => {
  const gt = { segments: [seg('s', 0, 60, { athlete_id: 'A' })], reviewed_ranges: [{ start_frame: 0, end_frame: 60 }],
    keyframes: [kf('k0', 's', 0, { x: 0.05, y: 0.4, w: 0.05, h: 0.1 }), kf('k1', 's', 59, { x: 0.05, y: 0.4, w: 0.05, h: 0.1 })] };
  const edl = { schema: 'edl/v1', output_id: 'reel-1', run_id: 'run-x', mapping: 'edl', mode: 'tracked_crop', source_sha256: SHA1,
    source: { width: 1920, height: 1080, fps: 30 }, output: { width: 1080, height: 1920, fps: 30 },
    shots: [{ out_start: 0, out_end: 60, src_start: 0, speed: 1, mode: 'tracked_crop', source_sha256: SHA1, source: { width: 1920, height: 1080, fps: 30 },
      crop_start: { cx: 1300, cy: 540, w: 606, h: 1080 } }] };
  const rv = R.buildReview({ report, predSources: [{ source_sha256: SHA1, events: [{ start_frame: 0, end_frame: 60, athlete_key: 'k' }] }],
    members: [{ sha256: SHA1, split: 'test', content: gt, owner_athlete_id: 'A' }], videos, athletes, edls: [edl] });
  assert.equal(rv.framing[0].status, 'EVALUATED');
  const f = rv.items.filter(i => i.category === 'framing');
  assert.equal(new Set(f.map(i => i.type)).size, f.length, 'one episode per problem, not one item per frame');
  const miss = f.find(i => i.type === 'missing_surfer');
  assert.equal(miss.frames, 60); assert.equal(miss.output_id, 'reel-1'); assert.equal(miss.video.name, 'DJI_0001.MP4'); assert.equal(miss.severity, 'bad');
});

test('loader: review of a stored evaluation uses only the evaluated split and is deterministic', async () => {
  const ctx = newCtx(); const raw = path.join(tmp('rv-'), 'raw');
  for (let i = 0; i < 2; i++) makeVideo(path.join(raw, `v${i}.mp4`), { seconds: 3, y: 10 + i * 20, tag: `r${i}` });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const db = ctx.db, srcs = db.prepare('select * from sources order by display_name').all();
  const ath = A.createAthlete(db, 'Surfer One');
  for (const s of srcs) { const c = A.emptyContent(); c.segments.push(seg('a', 10, 50, { athlete_id: ath.id })); c.reviewed_ranges.push({ start_frame: 0, end_frame: 90 });
    A.saveDraft(db, s.id, A.getDraft(db, s.id).version, c); A.approve(db, s.id, { expectedVersion: A.getDraft(db, s.id).version, acknowledgeUnresolved: true }); }
  const ds = D.freezeDataset(db, { name: 'd', sourceIds: srcs.map(s => s.id), policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
  const pr = E.importPredictions(db, { run_id: 'run-1', pipeline_version: 'abc', sources: [{ source_sha256: srcs[0].sha256, events: [{ start_frame: 10, end_frame: 50, athlete_key: 'k' }] }] });
  const ev = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pr.id });
  const r1 = R.reviewEvaluation(db, ev.id), r2 = R.reviewEvaluation(db, ev.id);
  assert.deepEqual(r1, r2);
  assert.equal(r1.summary.videos, 2); assert.equal(r1.summary.videos_without_prediction, 1);
  assert.ok(r1.items.some(i => i.type === 'video_not_processed' && i.video.name === srcs[1].display_name));
  assert.equal(r1.summary.matched_without_issue, 1);
  assert.throws(() => R.reviewEvaluation(db, 'nope'), e => e.code === 'NOT_FOUND');
});

test('a wave found under another sport is a sport error, not a poor cut', () => {
  const gt = { segments: [seg('t', 0, 300, { resolved_sport_id: 'tennis' })], keyframes: [], reviewed_ranges: [{ start_frame: 0, end_frame: 300 }] };
  const rv = R.buildReview({ report, predSources: [{ source_sha256: SHA1, events: [{ start_frame: 0, end_frame: 300, sport_id: 'football' }] }],
    members: [{ sha256: SHA1, split: 'test', content: gt, owner_athlete_id: null }], videos, athletes });
  assert.deepEqual(types(rv, 'selection_missed'), ['missed_wrong_sport']);
  assert.deepEqual(types(rv, 'selection_wrong_use'), [], 'explained once');
  assert.equal(rv.summary.missed, 1);
});
