// P0 BOX truthfulness (spec §21.2, §22.2 P0-1) and honest approval semantics (§22.2 P0-3) — hostile, direct-API tests.
// Every positive human decision must be bound to: exact source frame, segment, performer and the exact geometry looked at.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import { createApp } from '../server/app.mjs';
import * as A from '../server/annotations.mjs';
import { segmentTrackQa, upgradeLegacyBoxQA } from '../server/trackqa.mjs';

async function withSource(opts = {}) {
  const ctx = newCtx();
  const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), opts);
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const src = ctx.db.prepare('select * from sources').get();
  return { ctx, db: ctx.db, src };
}
let tick = 0;
const T = () => new Date(Date.UTC(2026, 0, 1) + ++tick * 1000).toISOString();
const B = (x, y = 0.3, w = 0.1, h = 0.2) => ({ x, y, w, h });
const K = (id, segment_id, frame, bbox, o = {}) => ({ id, segment_id, frame, bbox, visibility: 'visible', origin: 'manual', verification_status: 'unreviewed', ...o });
const V = (segment_id, frame, status, bbox, athlete_id, o = {}) => ({ segment_id, frame, status, bbox, athlete_id, verified_by: 'operator', verified_at: T(), ...o });
const code = c => e => e.code === c;

function base(ath) {
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: ath, decision: 'include', usability: 'usable' }));
  c.keyframes.push(K('k0', 's1', 0, B(0.1)), K('k30', 's1', 30, B(0.3)), K('k59', 's1', 59, B(0.5)));
  return c;
}

test('R1/R2: a verification is accepted only for a real box at that exact frame, segment and geometry', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  // Evidence elsewhere in the segment is NOT evidence for frame 15 (the audited P0 bypass).
  let c = base(a); c.box_verifications = [V('s1', 15, 'verified_correct', B(0.2), a)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('BOX_NOT_AT_FRAME'));
  // Claim without any geometry snapshot.
  c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', undefined, a)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('BOX_NOT_AT_FRAME'));
  // Geometry snapshot that does not match the box actually stored at that frame.
  c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.31), a)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('STALE_BOX_VERIFICATION'));
  // Box of ANOTHER segment at the same frame is not evidence for this segment.
  c = base(a); c.segments.push(seg('s2', 0, 60, { athlete_id: a, decision: 'exclude', usability: 'unusable', reason_codes: ['other'] }));
  c.keyframes.push(K('o15', 's2', 15, B(0.2)));
  c.box_verifications = [V('s1', 15, 'verified_correct', B(0.2), a)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('BOX_NOT_AT_FRAME'));
  // Out of segment range / malformed / unknown segment / missing reviewer.
  for (const bad of [V('s1', 60, 'verified_correct', B(0.5), a), V('s1', 1.5, 'verified_correct', B(0.5), a), V('nope', 30, 'verified_correct', B(0.3), a), { ...V('s1', 30, 'verified_correct', B(0.3), a), verified_by: '' }, { ...V('s1', 30, 'verified_correct', B(0.3), a), verified_at: 'yesterday' }, V('s1', 30, 'approved!!', B(0.3), a), V('s1', 30, 'verified_correct', { x: 0.95, y: 0.3, w: 0.1, h: 0.2 }, a)]) {
    c = base(a); c.box_verifications = [bad];
    assert.throws(() => A.saveDraft(db, src.id, 0, c), /./, JSON.stringify(bad));
  }
  // Valid: exact frame, exact geometry, current performer.
  c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), a)];
  assert.equal(A.saveDraft(db, src.id, 0, c).version, 1);
});

test('R3: drawing a box is not verifying it; keyframe flags cannot claim what the log does not show', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a);
  assert.equal(A.saveDraft(db, src.id, 0, c).version, 1);
  const st = A.sourceStates(db, src.id);
  assert.equal(st.box_qa.frames_verified, 0);
  assert.equal(st.box_qa.per_segment[0].status, 'not_checked');
  c.keyframes[1].verification_status = 'verified_correct';
  c.keyframes[1].verified_at = T(); c.keyframes[1].verified_by = 'operator';
  assert.throws(() => A.saveDraft(db, src.id, 1, c), code('STALE_BOX_VERIFICATION'));
});

test('R4: changing geometry after a verification invalidates it (refused until an explicit re-check/invalidation)', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), a)];
  A.saveDraft(db, src.id, 0, c);
  c.keyframes[1].bbox = B(0.35);
  assert.throws(() => A.saveDraft(db, src.id, 1, c), code('STALE_BOX_VERIFICATION'));
  c.box_verifications.push(V('s1', 30, 'unreviewed', B(0.35), a, { invalidation: 'geometry_changed', original_bbox: B(0.3) }));
  A.saveDraft(db, src.id, 1, c);
  assert.equal(A.sourceStates(db, src.id).box_qa.frames_verified, 0);
  // Re-check the new geometry: counts again.
  c.box_verifications.push(V('s1', 30, 'verified_correct', B(0.35), a));
  A.saveDraft(db, src.id, 2, c);
  assert.equal(A.sourceStates(db, src.id).box_qa.frames_verified, 1);
  // Deleting the keyframe while its verification is in force is refused.
  const d = structuredClone(c); d.keyframes.splice(1, 1);
  assert.throws(() => A.saveDraft(db, src.id, 3, d), code('BOX_NOT_AT_FRAME'));
});

test('R5: changing the performing surfer invalidates identity verifications; verifying without a performer is refused', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id, b = A.createAthlete(db, 'B').id;
  let c = base(null); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), null)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('BOX_IDENTITY_MISMATCH'));
  c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), b)];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('BOX_IDENTITY_MISMATCH'), 'decision recorded for a different surfer');
  c = base(a); c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), a)];
  A.saveDraft(db, src.id, 0, c);
  c.segments[0].athlete_id = b;
  assert.throws(() => A.saveDraft(db, src.id, 1, c), code('BOX_IDENTITY_MISMATCH'));
  // The catalog owner never makes a box pass (§21.2.6).
  db.prepare('update sources set owner_athlete_id=?, owner_status=? where id=?').run(b, 'assigned', src.id);
  assert.throws(() => A.saveDraft(db, src.id, 1, c), code('BOX_IDENTITY_MISMATCH'));
});

test('R6/R7: interpolation is not verification, and one checked frame never verifies a track', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a);
  for (let f = 10; f < 59; f += 10) if (f !== 30) c.keyframes.push(K(`i${f}`, 's1', f, B(0.1 + f / 150), { origin: 'interpolated' }));
  c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), a)];
  A.saveDraft(db, src.id, 0, c);
  const q = A.sourceStates(db, src.id).box_qa.per_segment[0];
  assert.equal(q.status, 'partially_checked');
  assert.equal(q.verified_frames, 1);
  assert.equal(q.interpolated_frames, 4);
  assert.deepEqual(q.missing_checkpoints, [0, 59]);
  // Verify start/middle/end: only then "verified in checked range" — still never "fully verified".
  c.box_verifications.push(V('s1', 0, 'verified_correct', B(0.1), a), V('s1', 59, 'verified_correct', B(0.5), a));
  c.track_qa_policy = { max_gap_frames: 30 };
  A.saveDraft(db, src.id, 1, c);
  const q2 = A.sourceStates(db, src.id).box_qa.per_segment[0];
  assert.equal(q2.status, 'verified_in_checked_range');
  assert.deepEqual(q2.checked_range, [0, 59]);
  // Sampling density is configurable and evidenced: a tighter policy downgrades the same evidence.
  c.track_qa_policy = { max_gap_frames: 10 };
  A.saveDraft(db, src.id, 2, c);
  assert.equal(A.sourceStates(db, src.id).box_qa.per_segment[0].status, 'partially_checked');
});

test('R7b: a segment with ONE box frame, verified, is still only partially checked', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: a, decision: 'include', usability: 'usable' }));
  c.keyframes.push(K('k30', 's1', 30, B(0.3)));
  c.box_verifications = [V('s1', 30, 'verified_correct', B(0.3), a)];
  A.saveDraft(db, src.id, 0, c);
  const q = A.sourceStates(db, src.id).box_qa.per_segment[0];
  assert.equal(q.status, 'partially_checked');
  assert.ok(q.event_span_checked_ratio < 0.05);
});

test('R8: crossings, occlusion, fast motion and exit/return are required checkpoints', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id, b = A.createAthlete(db, 'B').id;
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: a, decision: 'include', usability: 'usable', key_moments: { inflection_frames: [20] } }));
  c.segments.push(seg('s2', 0, 60, { athlete_id: b, decision: 'include', usability: 'usable' }));
  // A moves right, B moves left: they cross around frame 30. A jumps abruptly at 45->50 and leaves the frame at 55.
  c.keyframes.push(K('a0', 's1', 0, B(0.1)), K('a45', 's1', 45, B(0.7)), K('a50', 's1', 50, B(0.1, 0.6)), K('a55', 's1', 55, B(0.1, 0.6), { visibility: 'not_visible' }), K('a59', 's1', 59, B(0.1, 0.6)));
  c.keyframes.push(K('b0', 's2', 0, B(0.7)), K('b59', 's2', 59, B(0.1)));
  A.saveDraft(db, src.id, 0, c);
  const q = segmentTrackQa(A.getDraft(db, src.id).content, c.segments[0], 30);
  const reasons = Object.fromEntries(q.required_checkpoints.map(cp => [cp.frame, cp.reasons]));
  assert.ok(q.crossings.length >= 1, 'crossing detected');
  assert.ok(q.required_checkpoints.some(cp => cp.reasons.includes('crossing')));
  assert.ok(reasons[45].includes('large_jump') && reasons[50].includes('large_jump'));
  assert.ok(reasons[55].includes('visibility_not_visible'));
  assert.ok(reasons[20].includes('movement'));
  // A verified_correct decision on a not-visible box is refused; "occluded / not visible" is the honest decision.
  c.box_verifications = [V('s1', 55, 'verified_correct', B(0.1, 0.6), a)];
  assert.throws(() => A.saveDraft(db, src.id, 1, c), /מוסתר|לא נראה/);
  c.box_verifications = [V('s1', 55, 'occluded', B(0.1, 0.6), a)];
  A.saveDraft(db, src.id, 1, c);
});

test('R9: review evidence (reviewer, time, corrections) is append-only history; latest decision wins', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a);
  c.box_verifications = [V('s1', 30, 'wrong_performer', B(0.3), a, { notes: 'on the bystander' })];
  A.saveDraft(db, src.id, 0, c);
  assert.equal(A.sourceStates(db, src.id).box_qa.per_segment[0].status, 'needs_correction');
  c.keyframes[1].bbox = B(0.4); c.keyframes[1].verification_status = 'corrected';
  c.box_verifications.push(V('s1', 30, 'corrected', B(0.4), a, { original_bbox: B(0.3), corrected_bbox: B(0.4), verified_by: 'reviewer-2' }));
  A.saveDraft(db, src.id, 1, c);
  const saved = A.getDraft(db, src.id).content.box_verifications;
  assert.deepEqual(saved.map(v => v.status), ['wrong_performer', 'corrected']);
  assert.equal(saved[1].verified_by, 'reviewer-2');
  assert.notEqual(A.sourceStates(db, src.id).box_qa.per_segment[0].status, 'needs_correction');
});

test('R10 over HTTP: hostile documents cannot create a verification, and blocking items cannot be acknowledged away', async () => {
  const { ctx, src } = await withSource();
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base_ = `http://127.0.0.1:${server.address().port}`;
  const call = (p, o = {}) => fetch(base_ + p, { ...o, headers: { authorization: 'Bearer test-token', 'content-type': 'application/json', ...(o.headers || {}) } });
  try {
    const a = await (await call('/api/athletes', { method: 'POST', body: JSON.stringify({ label: 'A' }) })).json();
    let c = base(a.id); c.box_verifications = [V('s1', 15, 'verified_correct', B(0.2), a.id)];
    let r = await call(`/api/sources/${src.id}/draft`, { method: 'PUT', body: JSON.stringify({ expected_version: 0, content: c }) });
    assert.equal(r.status, 400); assert.equal((await r.json()).code, 'BOX_NOT_AT_FRAME');
    c = base(a.id); c.box_verifications = [V('s1', 30, 'wrong_performer', B(0.3), a.id)];
    r = await call(`/api/sources/${src.id}/draft`, { method: 'PUT', body: JSON.stringify({ expected_version: 0, content: c }) });
    assert.equal(r.status, 200);
    r = await call(`/api/sources/${src.id}/approve`, { method: 'POST', body: JSON.stringify({ expected_version: 1, acknowledge_unresolved: true }) });
    assert.equal(r.status, 409);
    const j = await r.json();
    assert.equal(j.code, 'BLOCKING_ITEMS');
    assert.equal(j.unresolved.blocking.boxes_needing_correction, 1);
    r = await call(`/api/sources/${src.id}/states`);
    const st = await r.json();
    assert.equal(st.workflow, 'needs_review');
    assert.equal(st.ground_truth.approved, false);
  } finally { server.closeAllConnections(); server.close(); }
});

test('new events: usability and dataset decision both start uncertain; approval requires active decisions or audited acknowledgement', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = A.emptyContent();
  // What the UI's createSegment produces now.
  c.segments.push(seg('s1', 0, 60, { athlete_id: a, decision: 'uncertain', usability: 'uncertain' }));
  A.saveDraft(db, src.id, 0, c);
  const u = A.unresolved(A.getDraft(db, src.id).content, src);
  assert.equal(u.uncertain_segments, 1); assert.equal(u.usability_undecided, 1);
  assert.throws(() => A.approve(db, src.id, { expectedVersion: 1 }), code('UNRESOLVED_ITEMS'));
  // Partial/unusable without a reason is an open item, not silently accepted.
  c.segments[0] = { ...c.segments[0], decision: 'include', usability: 'partially_usable', reason_codes: [] };
  A.saveDraft(db, src.id, 1, c);
  assert.equal(A.unresolved(A.getDraft(db, src.id).content, src).missing_reason_codes, 1);
  c.segments[0].reason_codes = ['missing_landing'];
  A.saveDraft(db, src.id, 2, c);
  const out = A.approve(db, src.id, { expectedVersion: 3, reason: 'pilot' });
  assert.equal(out.unchanged, false);
  assert.deepEqual(out.approval_caveats.acknowledged, {});
  assert.equal(out.approval_caveats.scope, 'source');
  const st = A.sourceStates(db, src.id);
  assert.equal(st.workflow, 'approved');
  assert.equal(st.box_qa.frames_verified, 0, 'approval never converts anything into verified boxes');
  assert.deepEqual(st.datasets.frozen_in, [], 'approved is not frozen');
});

test('acknowledged approvals record exact caveats in the audit log; unverified boxes are recorded as a caveat, never as verified', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a); c.segments[0].decision = 'uncertain';
  A.saveDraft(db, src.id, 0, c);
  const out = A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true, reason: 'explicit pilot' });
  assert.equal(out.approval_caveats.acknowledged.uncertain_segments, 1);
  const audit = db.prepare(`select detail from audit_log where action='approve_revision' order by id desc limit 1`).get();
  const d = JSON.parse(audit.detail);
  assert.equal(d.approval_caveats.acknowledged.uncertain_segments, 1);
  assert.equal(d.approval_caveats.track_qa[0].status, 'not_checked');
});

test('legacy drafts: unbound "verified" entries are neutralized on read with history kept; approved revisions untouched', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  // Write a draft in the pre-fix format directly (bypassing validation), as an old Studio build could have.
  const legacy = base(a);
  legacy.keyframes[1].verification_status = 'verified_correct';
  legacy.box_verifications = [
    { segment_id: 's1', frame: 30, athlete_id: a, status: 'verified_correct', verified_by: 'operator', verified_at: '2026-10-01T00:00:00.000Z' },
    { segment_id: 's1', frame: 15, athlete_id: a, status: 'verified_correct', verified_by: 'operator', verified_at: '2026-10-01T00:00:00.000Z' },
  ];
  db.prepare('insert into annotation_drafts(source_id,version,content,base_revision_id,updated_at) values(?,?,?,?,?)').run(src.id, 3, JSON.stringify(legacy), null, '2026-10-01T00:00:00.000Z');
  const d = A.getDraft(db, src.id);
  assert.equal(d.legacy_box_qa_upgraded, true);
  const vs = d.content.box_verifications;
  // Frame 30 had a real box: bound. Frame 15 had none: neutralized + explicit invalidation, original kept.
  assert.deepEqual(vs.find(v => v.frame === 30).bbox, B(0.3));
  assert.equal(vs.find(v => v.frame === 15 && v.legacy_status === 'verified_correct')?.status, 'unreviewed');
  // The upgraded document is valid under the strict validator.
  assert.equal(A.saveDraft(db, src.id, 3, d.content).version, 4);
  const q = A.sourceStates(db, src.id).box_qa.per_segment[0];
  assert.equal(q.verified_frames, 1);
  // Pure function: idempotent.
  assert.equal(upgradeLegacyBoxQA(A.getDraft(db, src.id).content).changed, false);
});

test('4K source shown through a low-resolution proxy: boxes and frames are stored in ORIGINAL source coordinates', async () => {
  const { ctx, src } = await withSource({ w: 3840, h: 2160, fps: 30, seconds: 2 });
  assert.equal(src.width, 3840); assert.equal(src.height, 2160);
  const a = A.createAthlete(ctx.db, 'A').id;
  // A box drawn on the 640px proxy at pixel (64,72)-(128,144) is the same normalized box on the 4K original.
  const proxyW = 640, proxyH = 360, nb = { x: 64 / proxyW, y: 72 / proxyH, w: 64 / proxyW, h: 72 / proxyH };
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, src.frame_count, { athlete_id: a, decision: 'include', usability: 'usable' }));
  const last = src.frame_count - 1;
  c.keyframes.push(K('k', 's1', last, nb));
  c.box_verifications = [V('s1', last, 'verified_correct', nb, a)];
  A.saveDraft(ctx.db, src.id, 0, c);
  const stored = A.getDraft(ctx.db, src.id).content.keyframes[0];
  assert.equal(stored.frame, last, 'frame index is the source frame, not a proxy frame');
  assert.deepEqual({ x: Math.round(stored.bbox.x * src.width), y: Math.round(stored.bbox.y * src.height), w: Math.round(stored.bbox.w * src.width), h: Math.round(stored.bbox.h * src.height) }, { x: 384, y: 432, w: 384, h: 432 });
  // A frame beyond the source's frame count is refused even if a proxy were longer.
  c.keyframes.push(K('k2', 's1', src.frame_count, nb));
  assert.throws(() => A.saveDraft(ctx.db, src.id, 1, c), /./);
});

// ---- regressions from the independent review ----
test('review#2: a future-dated decision cannot shadow a later wrong-performer flag; future timestamps refused', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = base(a);
  c.box_verifications = [V('s1', 0, 'verified_correct', B(0.1), a, { verified_at: '9999-01-01T00:00:00.000Z' })];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), /בעתיד/);
  c.box_verifications = [V('s1', 0, 'verified_correct', B(0.1), a, { verified_at: '2026-01-01T00:00:00.000Z' }), V('s1', 30, 'verified_correct', B(0.3), a), V('s1', 59, 'verified_correct', B(0.5), a),
    V('s1', 0, 'wrong_performer', B(0.1), a, { verified_at: '2020-01-01T00:00:00.000Z' })];      // appended later, OLDER timestamp
  A.saveDraft(db, src.id, 0, c);
  assert.equal(A.sourceStates(db, src.id).box_qa.per_segment[0].status, 'needs_correction', 'array order, not client time, decides');
  assert.throws(() => A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true }), code('BLOCKING_ITEMS'));
});

test('review#3: "cannot determine" at a crossing never satisfies the checkpoint of a verified track', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id, b = A.createAthlete(db, 'B').id;
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: a, usability: 'usable' }), seg('s2', 0, 60, { athlete_id: b, usability: 'usable', decision: 'exclude', reason_codes: ['other'] }));
  c.keyframes.push(K('a0', 's1', 0, B(0.1)), K('a59', 's1', 59, B(0.7)), K('b0', 's2', 0, B(0.7)), K('b59', 's2', 59, B(0.1)));
  c.box_verifications = [V('s1', 0, 'verified_correct', B(0.1), a), V('s1', 59, 'verified_correct', B(0.7), a)];
  for (let f = 1; f < 59; f++) c.box_verifications.push(V('s1', f, 'indeterminate', undefined, a));
  c.track_qa_policy = { max_gap_frames: 100 };
  A.saveDraft(db, src.id, 0, c);
  const q = A.sourceStates(db, src.id).box_qa.per_segment.find(x => x.segment_id === 's1');
  assert.ok(q.crossings >= 1);
  assert.notEqual(q.status, 'verified_in_checked_range');
  assert.ok(q.missing_checkpoints.length >= 1);
});

test('review#5/#6: wrong flag blocks even with no keyframes; excluding the segment clears the block', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: a, usability: 'usable' }));
  c.box_verifications = [V('s1', 10, 'wrong_performer', B(0.1), a)];
  A.saveDraft(db, src.id, 0, c);
  assert.throws(() => A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true }), code('BLOCKING_ITEMS'));
  c.segments[0] = { ...c.segments[0], decision: 'exclude', usability: 'unusable', reason_codes: ['unclear_identity'] };
  A.saveDraft(db, src.id, 1, c);
  assert.equal(A.approve(db, src.id, { expectedVersion: 2 }).unchanged, false);
});

test('review#7/#8: duplicate (segment, frame) keyframes and null log entries are 400s', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  let c = base(a); c.keyframes.push(K('dup', 's1', 30, B(0.35)));
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('INVALID_INPUT'));
  c = base(a); c.box_verifications = [null];
  assert.throws(() => A.saveDraft(db, src.id, 0, c), code('INVALID_INPUT'));
});

test('review#9: track QA on long 4K events stays fast (20 segments x 18,000 frames)', async () => {
  const c = A.emptyContent();
  const ids = [];
  for (let i = 0; i < 20; i++) {
    c.segments.push(seg(`s${i}`, 0, 18000, { athlete_id: `ath${i}` })); ids.push(`s${i}`);
    for (let f = 0; f < 18000; f += 5) c.keyframes.push(K(`k${i}-${f}`, `s${i}`, f, B(0.02 + (i * 0.04 + f / 18000 * 0.5) % 0.8)));
  }
  const t = Date.now();
  for (const s of c.segments) segmentTrackQa(c, s, 60);
  assert.ok(Date.now() - t < 20000, `took ${Date.now() - t} ms`);
});
