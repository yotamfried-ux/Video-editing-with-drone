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

  // Attempting to save an interpolated keyframe marked as 'verified_correct' without explicit verification metadata
  const badContent = A.emptyContent();
  badContent.segments.push(seg('s1', 10, 80, { athlete_id: ath.id, event_type: 'wave_ride', decision: 'include' }));
  badContent.keyframes.push({
    id: 'k-interp-fake-verified',
    segment_id: 's1',
    frame: 35,
    bbox: { x: 0.2, y: 0.2, w: 0.1, h: 0.1 },
    visibility: 'visible',
    origin: 'interpolated',
    verification_status: 'verified_correct', // Rule violation: cannot claim verified without verification evidence
  });

  assert.throws(
    () => A.saveDraft(db, src.id, 0, badContent),
    /פריים אינטרפולציה לא יכול להיחשב מאומת ללא אימות מפורש/
  );

  // Correct workflow: manual keyframe with verified provenance
  const goodContent = A.emptyContent();
  goodContent.segments.push(seg('s1', 10, 80, { athlete_id: ath.id, event_type: 'wave_ride', decision: 'include' }));
  goodContent.keyframes.push({
    id: 'k-manual',
    segment_id: 's1',
    frame: 10,
    bbox: { x: 0.2, y: 0.2, w: 0.1, h: 0.1 },
    visibility: 'visible',
    origin: 'manual',
    verification_status: 'verified_correct',
    verified_at: new Date().toISOString(),
    verified_by: 'annotator_1',
  });
  // Interpolated keyframe correctly left unreviewed
  goodContent.keyframes.push({
    id: 'k-interpolated',
    segment_id: 's1',
    frame: 45,
    bbox: { x: 0.25, y: 0.25, w: 0.1, h: 0.1 },
    visibility: 'visible',
    origin: 'interpolated',
    verification_status: 'unreviewed',
  });
  // Box verification records for sampled frames (start, mid, end, inflection)
  goodContent.box_verifications = [
    {
      segment_id: 's1',
      frame: 10,
      athlete_id: ath.id,
      status: 'verified_correct',
      verified_by: 'annotator_1',
      verified_at: new Date().toISOString(),
      notes: 'Clean takeoff, box centered on athlete',
    },
    {
      segment_id: 's1',
      frame: 45,
      athlete_id: ath.id,
      status: 'corrected',
      verified_by: 'annotator_1',
      verified_at: new Date().toISOString(),
      original_bbox: { x: 0.25, y: 0.25, w: 0.1, h: 0.1 },
      corrected_bbox: { x: 0.27, y: 0.23, w: 0.09, h: 0.12 },
      notes: 'Surfer ducked below wave crest; corrected vertical bounds',
    },
    {
      segment_id: 's1',
      frame: 70,
      athlete_id: ath.id,
      status: 'wrong_performer',
      verified_by: 'annotator_1',
      verified_at: new Date().toISOString(),
      notes: 'Another surfer crossed in front; tracking jumped to bystander',
    },
  ];
  goodContent.reviewed_ranges.push({ start_frame: 0, end_frame: 100 });

  const saveRes = A.saveDraft(db, src.id, 0, goodContent);
  assert.equal(saveRes.version, 1);

  // Reload and confirm all verification records preserved
  const loaded = A.getDraft(db, src.id);
  assert.equal(loaded.content.box_verifications.length, 3);
  assert.equal(loaded.content.box_verifications[0].status, 'verified_correct');
  assert.equal(loaded.content.box_verifications[1].status, 'corrected');
  assert.equal(loaded.content.box_verifications[2].status, 'wrong_performer');
  assert.deepEqual(loaded.content.box_verifications[1].corrected_bbox, { x: 0.27, y: 0.23, w: 0.09, h: 0.12 });
});
