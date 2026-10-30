// M5: analytic transforms and editing-quality metrics.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as L from '../server/edl.mjs';
import { seg, kf } from './helpers.mjs';

const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) <= e, `${a} != ${b}`);
const edl = (o = {}) => ({ schema: 'edl/v1', output_id: 'o1', run_id: 'r1', source_sha256: 'a'.repeat(64),
  source: { width: 1920, height: 1080 }, output: { width: 1080, height: 1920, fps: 30 }, mode: 'tracked_crop', rotation: 0,
  shots: [{ out_start: 0, out_end: 100, src_start: 0, speed: 1, crop_start: { cx: 1008, cy: 540, w: 607.5, h: 1080 } }], ...o });
const BOX = { x: 0.5, y: 0.45, w: 0.05, h: 0.1 }; // centre px (1008, 540)
const gt = (o = {}) => ({ schema: 1, segments: [seg('s', 0, 100, o.seg)], keyframes: [kf('a', 's', 0, BOX), kf('b', 's', 99, BOX)], reviewed_ranges: [{ start_frame: 0, end_frame: 100 }] });

test('contain: full 16:9 frame letterboxed in 9:16, centred', () => {
  const e = edl({ mode: 'contain', source: { width: 3840, height: 2160 }, output: { width: 2160, height: 3840, fps: 30 },
    shots: [{ out_start: 0, out_end: 10, src_start: 0, crop_start: { cx: 1920, cy: 1080, w: 3840, h: 2160 } }] });
  const { box, region, scale } = L.sourceBoxToOutput(e, e.shots[0].crop_start, { x: 0.45, y: 0.45, w: 0.1, h: 0.1 });
  near(scale, 0.5625); near((box.x1 + box.x2) / 2, 1080); near((box.y1 + box.y2) / 2, 1920);
  near(region.y1, 1312.5); near(region.y2, 3840 - 1312.5); near(region.x1, 0); near(region.x2, 2160);
});

test('tracked crop: resize math is exact', () => {
  const e = edl({ output: { width: 2160, height: 3840, fps: 30 } });
  const crop = { cx: 1000, cy: 1000, w: 1080, h: 1920 };
  const t = L.makeTransform(e, crop);
  assert.equal(t.scale, 2);
  assert.deepEqual(t.pt(1000, 1000), [1080, 1920]);
  assert.deepEqual(t.pt(1100, 900), [1280, 1720]);
});

test('rotation: 90° clockwise swaps axes and fits the canvas', () => {
  const e = edl({ rotation: 90, output: { width: 2160, height: 3840, fps: 30 } });
  const t = L.makeTransform(e, { cx: 1000, cy: 1000, w: 1080, h: 1920 });
  near(t.scale, 1.125);
  const [x, y] = t.pt(1100, 1000); // +100 px right of centre -> rotates to +y (down) by 112.5
  near(x, 1080); near(y, 1920 + 112.5);
  const [x2, y2] = t.pt(1000, 1100); // +100 down -> rotates to -x
  near(x2, 1080 - 112.5); near(y2, 1920);
});

test('padding: crop larger than source gives pad bars and partial visibility', () => {
  const e = edl();
  const crop = { cx: 100, cy: 540, w: 607.5, h: 1080 }; // crop window hangs off the left edge of the source
  const { region } = L.sourceBoxToOutput(e, crop, { x: 0.0, y: 0.4, w: 0.02, h: 0.1 });
  assert.ok(region.x1 > 0, 'pad bar on the left');
});

test('centred surfer scores zero centering error and full visibility', () => {
  const r = L.evaluateEditing(edl(), gt({ seg: { framing_mode: 'geometric_center' } }));
  assert.equal(r.status, 'EVALUATED'); near(r.centering.median, 0, 1e-9); assert.equal(r.visibility.fully_visible, 1);
  assert.equal(r.errors.length, 0); assert.equal(r.coverage.coverage_ratio, 1);
});

test('off-centre surfer triggers centering deviation; lead-room target is not penalised', () => {
  const off = edl({ shots: [{ out_start: 0, out_end: 100, src_start: 0, crop_start: { cx: 858, cy: 540, w: 607.5, h: 1080 } }] });
  const bad = L.evaluateEditing(off, gt({ seg: { framing_mode: 'geometric_center' } }));
  near(bad.centering.median, 0.24691358, 1e-4); assert.equal(bad.errors.filter(e => e.type === 'centering_error').length, 100);
  const lead = L.evaluateEditing(off, gt({ seg: { framing_mode: 'directional_lead_room', target: { x: 0.5 + 0.2469135802, y: 0.5 } } }));
  near(lead.centering.median, 0, 1e-4); assert.equal(lead.errors.filter(e => e.type === 'centering_error').length, 0);
});

test('contain is never scored as a centering/crop failure', () => {
  const e = edl({ mode: 'contain', shots: [{ out_start: 0, out_end: 100, src_start: 0, crop_start: { cx: 960, cy: 540, w: 1920, h: 1080 } }] });
  const r = L.evaluateEditing(e, gt({ seg: { framing_mode: 'geometric_center' } }));
  assert.equal(r.centering.scored_frames, 0); assert.match(r.centering.note, /contain/);
  assert.equal(r.visibility.fully_visible, 1); assert.equal(r.errors.length, 0);
});

test('clipped surfer is reported with exact output and source frames', () => {
  const clip = edl({ shots: [{ out_start: 0, out_end: 100, src_start: 10, crop_start: { cx: 1008 - 330, cy: 540, w: 607.5, h: 1080 } }] });
  const g = gt(); g.segments[0].start_frame = 0; g.segments[0].end_frame = 200; g.keyframes = [kf('a', 's', 0, BOX), kf('b', 's', 199, BOX)]; g.reviewed_ranges = [{ start_frame: 0, end_frame: 200 }];
  const r = L.evaluateEditing(clip, g);
  const miss = r.errors.filter(e => e.type === 'partial_clipping');
  assert.equal(miss.length, 100); near(miss[0].visible_fraction, 21.75 / 96, 1e-5); assert.equal(miss[0].src_frame, miss[0].out_frame + 10, 'exact source frame via EDL');
});

test('sudden crop jump is flagged at the exact frame; smooth pan is not', () => {
  const pan = edl({ shots: [{ out_start: 0, out_end: 100, src_start: 0, crop_start: { cx: 900, cy: 540, w: 607.5, h: 1080 }, crop_end: { cx: 1100, cy: 540, w: 607.5, h: 1080 } }] });
  assert.equal(L.evaluateEditing(pan, gt()).smoothness.crop_jumps, 0);
  const jumpy = edl({ shots: [{ out_start: 0, out_end: 3, src_start: 0, crop_start: { cx: 600, cy: 540, w: 607.5, h: 1080 }, crop_end: { cx: 1400, cy: 540, w: 607.5, h: 1080 } }] });
  const j = L.evaluateEditing(jumpy, gt()).errors.filter(x => x.type === 'crop_jump');
  assert.deepEqual(j.map(x => x.out_frame), [1, 2]);
});

test('identity swap (pipeline tracked a different person) is flagged', () => {
  const e = edl(); e.subject_track = [{ src_frame: 10, bbox: { x: 0.1, y: 0.1, w: 0.05, h: 0.1 } }, { src_frame: 20, bbox: BOX }];
  const r = L.evaluateEditing(e, gt());
  const w = r.errors.filter(x => x.type === 'wrong_surfer'); assert.equal(w.length, 1); assert.equal(w[0].src_frame, 10);
});

test('missing or visually-matched EDL is NOT_EVALUABLE, never a pass', () => {
  for (const x of [null, edl({ mapping: 'visual_match' })]) {
    const r = L.evaluateEditing(x, gt());
    assert.equal(r.status, 'NOT_EVALUABLE'); assert.equal(r.reason, 'EDL_UNVERIFIED'); assert.equal(r.mapping, 'unverified_mapping'); assert.equal(r.centering, undefined);
  }
});

test('unreviewed frames are excluded from scoring and the denominator is reported', () => {
  const g = gt(); g.reviewed_ranges = [{ start_frame: 0, end_frame: 40 }];
  const r = L.evaluateEditing(edl(), g);
  assert.equal(r.coverage.evaluated_frames, 40); assert.equal(r.coverage.unreviewed_or_unavailable, 60);
});

test('crop proposal never mutates anything and respects target mode', () => {
  const p = L.proposeCrop({ source: { width: 1920, height: 1080 }, bbox: BOX, mode: 'geometric_center' });
  near(p.cx, 1008, 1e-6); assert.equal(p.status, 'proposal');
  const lead = L.proposeCrop({ source: { width: 1920, height: 1080 }, bbox: BOX, mode: 'directional_lead_room', target: { x: 0.35, y: 0.5 } });
  assert.ok(lead.cx > p.cx, 'crop shifts so the surfer sits left of centre');
});
