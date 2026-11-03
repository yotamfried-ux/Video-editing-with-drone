// Tests for Precision Studio V2: Box QA, temporal verification, usability taxonomy, and key moments.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';

async function withSource() {
  const ctx = newCtx();
  const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'));
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const src = ctx.db.prepare('select * from sources').get();
  return { ctx, db: ctx.db, src };
}

test('usability taxonomy, structured reasons, and explicit GT decision round-trip', async () => {
  const { db, src } = await withSource();
  const ath = A.createAthlete(db, 'Surfer Pro');

  const c = A.emptyContent();
  c.segments.push(seg('s1', 10, 80, {
    athlete_id: ath.id,
    event_type: 'wave_ride',
    decision: 'exclude', // Explicit exclude decision
    usability: 'partially_usable',
    reason_codes: ['missing_takeoff', 'occlusion'],
    reason_detail: 'Wave was caught outside frame; obstructed by whitewater at frame 45',
    key_moments: {
      takeoff_frame: 15,
      peak_frame: 40,
      landing_frame: 75,
      inflection_frames: [30, 50],
    },
    needs_review: true,
    review_reason: 'Check if wave counts as completed',
  }));
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 100 });

  const res = A.saveDraft(db, src.id, 0, c);
  assert.equal(res.version, 1);

  // Reload and verify all fields preserved exactly
  const loaded = A.getDraft(db, src.id);
  const s = loaded.content.segments[0];
  assert.equal(s.decision, 'exclude');
  assert.equal(s.usability, 'partially_usable');
  assert.deepEqual(s.reason_codes, ['missing_takeoff', 'occlusion']);
  assert.equal(s.key_moments.peak_frame, 40);
  assert.deepEqual(s.key_moments.inflection_frames, [30, 50]);
  assert.equal(s.needs_review, true);
  assert.equal(A.annotationStatus(db, src.id), 'needs_review');
});

test('box verification provenance: interpolated frames cannot be marked verified_correct without explicit verification', async () => {
  const { db, src } = await withSource();
  const ath = A.createAthlete(db, 'Surfer Pro');
  const T = i => new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString();

  const badContent = A.emptyContent();
  badContent.segments.push(seg('s1', 10, 80, { athlete_id: ath.id, event_type: 'wave_ride', decision: 'include' }));
  badContent.keyframes.push({ id: 'k-interp-fake-verified', segment_id: 's1', frame: 35, bbox: { x: 0.2, y: 0.2, w: 0.1, h: 0.1 },
    visibility: 'visible', origin: 'interpolated', verification_status: 'verified_correct' });
  assert.throws(() => A.saveDraft(db, src.id, 0, badContent), /פריים אינטרפולציה לא יכול להיחשב מאומת ללא אימות מפורש/);

  // Correct workflow: each human decision is bound to the exact frame, geometry and performer it attests.
  const b10 = { x: 0.2, y: 0.2, w: 0.1, h: 0.1 }, b45 = { x: 0.27, y: 0.23, w: 0.09, h: 0.12 }, b70 = { x: 0.3, y: 0.3, w: 0.1, h: 0.1 };
  const good = A.emptyContent();
  good.segments.push(seg('s1', 10, 80, { athlete_id: ath.id, event_type: 'wave_ride', decision: 'include' }));
  good.keyframes.push({ id: 'k-manual', segment_id: 's1', frame: 10, bbox: b10, visibility: 'visible', origin: 'manual', verification_status: 'verified_correct' });
  // Interpolated position checked by a human and corrected: origin stays 'interpolated'; provenance is in the log.
  good.keyframes.push({ id: 'k-interpolated', segment_id: 's1', frame: 45, bbox: b45, visibility: 'visible', origin: 'interpolated', verification_status: 'corrected' });
  good.keyframes.push({ id: 'k-70', segment_id: 's1', frame: 70, bbox: b70, visibility: 'visible', origin: 'interpolated', verification_status: 'wrong_performer' });
  good.box_verifications = [
    { segment_id: 's1', frame: 10, athlete_id: ath.id, status: 'verified_correct', bbox: b10, verified_by: 'annotator_1', verified_at: T(1), notes: 'Clean takeoff' },
    { segment_id: 's1', frame: 45, athlete_id: ath.id, status: 'corrected', bbox: b45, original_bbox: { x: 0.25, y: 0.25, w: 0.1, h: 0.1 }, corrected_bbox: b45, verified_by: 'annotator_1', verified_at: T(2) },
    { segment_id: 's1', frame: 70, athlete_id: ath.id, status: 'wrong_performer', bbox: b70, verified_by: 'annotator_1', verified_at: T(3), notes: 'tracking jumped to bystander' },
  ];
  assert.equal(A.saveDraft(db, src.id, 0, good).version, 1);
  const loaded = A.getDraft(db, src.id);
  assert.equal(loaded.content.box_verifications.length, 3);
  assert.deepEqual(loaded.content.box_verifications.map(v => v.status), ['verified_correct', 'corrected', 'wrong_performer']);
  assert.deepEqual(loaded.content.box_verifications[1].corrected_bbox, b45);
  assert.equal(loaded.legacy_box_qa_upgraded, false);
});

test('box drawing and modification requires explicit human verification; cannot auto-verify', async () => {
  const { db, src } = await withSource();
  const ath1 = A.createAthlete(db, 'Surfer One');
  const ath2 = A.createAthlete(db, 'Surfer Two');
  const box = { x: 0.1, y: 0.1, w: 0.2, h: 0.2 };
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 100, { athlete_id: ath1.id, event_type: 'wave_ride', decision: 'include' }));
  // 1. Drawing is not verifying: a new box is saved unreviewed.
  c.keyframes.push({ id: 'k1', segment_id: 's1', frame: 20, bbox: box, visibility: 'visible', origin: 'manual', verification_status: 'unreviewed', verified_at: null, verified_by: null });
  A.saveDraft(db, src.id, 0, c);
  assert.equal(A.getDraft(db, src.id).content.keyframes[0].verification_status, 'unreviewed');
  // 2. A keyframe flag alone can never claim verification.
  c.keyframes[0].verification_status = 'verified_correct'; c.keyframes[0].verified_at = '2026-01-01T00:00:00.000Z';
  assert.throws(() => A.saveDraft(db, src.id, 1, c), e => e.code === 'STALE_BOX_VERIFICATION');
  // 3. Explicit bound decision.
  c.box_verifications = [{ segment_id: 's1', frame: 20, athlete_id: ath1.id, status: 'verified_correct', bbox: { ...box }, verified_by: 'coach', verified_at: '2026-01-01T00:00:01.000Z' }];
  A.saveDraft(db, src.id, 1, c);
  assert.equal(A.getDraft(db, src.id).content.box_verifications[0].status, 'verified_correct');
  // 4. Changing the performer while the old identity decision is still in force is refused...
  c.segments[0].athlete_id = ath2.id;
  assert.throws(() => A.saveDraft(db, src.id, 2, c), e => e.code === 'BOX_IDENTITY_MISMATCH');
  // ...until an explicit invalidation is appended (history is kept, not rewritten).
  c.keyframes[0].verification_status = 'unreviewed';
  c.box_verifications.push({ segment_id: 's1', frame: 20, athlete_id: ath2.id, status: 'unreviewed', invalidation: 'performer_changed', bbox: { ...box }, verified_by: 'operator', verified_at: '2026-01-01T00:00:02.000Z' });
  A.saveDraft(db, src.id, 2, c);
  const loaded = A.getDraft(db, src.id).content;
  assert.equal(loaded.box_verifications.length, 2);
  assert.equal(loaded.box_verifications[0].status, 'verified_correct', 'the earlier decision remains as history');
  assert.equal(loaded.keyframes[0].verification_status, 'unreviewed');
});

test('box QA invariants: cannot verify non-existent box; geometry change resets verification; athlete separation', async () => {
  const { db, src } = await withSource();
  const ath = A.createAthlete(db, 'Surfer Ace');
  const b = { x: 0.2, y: 0.2, w: 0.1, h: 0.1 };
  const c = A.emptyContent();
  c.segments.push(seg('s1', 10, 80, { athlete_id: ath.id, event_type: 'wave_ride', decision: 'include' }));
  c.box_verifications = [{ segment_id: 's1', frame: 25, athlete_id: ath.id, status: 'verified_correct', bbox: b, verified_by: 'coach', verified_at: '2026-01-01T00:00:00.000Z' }];
  // 1. No box at frame 25 -> refused, even though the claim carries a bbox.
  assert.throws(() => A.saveDraft(db, src.id, 0, c), e => e.code === 'BOX_NOT_AT_FRAME');
  // 2. Box exists at that exact frame with that geometry -> accepted.
  c.keyframes.push({ id: 'k1', segment_id: 's1', frame: 25, bbox: { ...b }, visibility: 'visible', origin: 'manual', verification_status: 'verified_correct' });
  assert.equal(A.saveDraft(db, src.id, 0, c).version, 1);
  // 3. Geometry modified without a new decision -> stale, refused.
  c.keyframes[0].bbox = { x: 0.25, y: 0.25, w: 0.12, h: 0.12 };
  assert.throws(() => A.saveDraft(db, src.id, 1, c), e => e.code === 'STALE_BOX_VERIFICATION');
  c.keyframes[0].verification_status = 'unreviewed';
  c.box_verifications.push({ segment_id: 's1', frame: 25, athlete_id: ath.id, status: 'unreviewed', invalidation: 'geometry_changed', bbox: { ...c.keyframes[0].bbox }, original_bbox: b, verified_by: 'operator', verified_at: '2026-01-01T00:00:01.000Z' });
  assert.equal(A.saveDraft(db, src.id, 1, c).version, 2);
  const loaded = A.getDraft(db, src.id).content;
  assert.equal(loaded.keyframes[0].verification_status, 'unreviewed');
  assert.equal(loaded.box_verifications.at(-1).invalidation, 'geometry_changed');
});
