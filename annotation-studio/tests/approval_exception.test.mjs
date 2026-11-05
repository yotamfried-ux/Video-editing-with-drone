// Approval by exception (operator principle, 2026-11-05): the operator watches the video, fixes only what is wrong and
// approves. The approval records every box not marked wrong, inside the watched part, as verified_correct — in the same
// transaction as the immutable revision — and the training export reads the verified boxes from that revision.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as QC from '../server/quickcatalog.mjs';
import { freezeDataset, exportJsonl } from '../server/datasets.mjs';
import { verifiedBoxes, approvalPreview, latestByFrame } from '../server/trackqa.mjs';

async function withSource() {
  const ctx = newCtx();
  const raw = path.join(tmp('appr-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), {});
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const src = ctx.db.prepare('select * from sources').get();
  return { ctx, db: ctx.db, src };
}
let tick = 0;
const T = () => new Date(Date.UTC(2026, 0, 1) + ++tick * 1000).toISOString();
const B = (x, y = 0.3, w = 0.1, h = 0.2) => ({ x, y, w, h });
const K = (id, segment_id, frame, bbox, o = {}) => ({ id, segment_id, frame, bbox, visibility: 'visible', origin: 'suggested', verification_status: 'unreviewed', ...o });
// one event of a known surfer, 0-60, boxes every 6 frames (like the tracker writes them)
function content(ath, { watched = [[0, 60]] } = {}) {
  const c = A.emptyContent();
  c.segments.push(seg('s1', 0, 60, { athlete_id: ath }));
  for (let f = 0; f < 60; f += 6) c.keyframes.push(K(`k${f}`, 's1', f, B(0.1 + f / 200)));
  c.reviewed_ranges = watched.map(([a, b]) => ({ start_frame: a, end_frame: b }));
  return c;
}
const rev = (db, id) => JSON.parse(db.prepare('select content from annotation_revisions where source_id=? order by seq desc limit 1').get(id).content);
const draftRow = (db, id) => db.prepare('select version, content from annotation_drafts where source_id=?').get(id);
const approve = (db, id, o = {}) => A.approve(db, id, { expectedVersion: draftRow(db, id).version, acceptByException: true, acknowledgeUnresolved: true, ...o });

test('1. fully watched, nothing marked: approval verifies every box, atomically with the revision', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a));
  assert.deepEqual(approvalPreview(A.getDraft(db, src.id).content), { to_verify: 10, already_verified: 0, marked: 0, not_checked: 0, events_checked: 1, events: 1 });
  const out = approve(db, src.id);
  assert.equal(out.accepted_by_exception, 10);
  const r = rev(db, src.id);
  assert.equal(r.box_verifications.length, 10);
  assert.ok(r.box_verifications.every(v => v.status === 'verified_correct' && v.method === 'exception_review' && v.athlete_id === a && v.bbox));
  assert.ok(r.keyframes.every(k => k.verification_status === 'verified_correct'));
  assert.equal(verifiedBoxes(r).length, 10);
  // the draft carries the same decisions as a NEW version (open pages reload it) and equals the approved revision
  const d = A.getDraft(db, src.id);
  assert.equal(d.version, 2); assert.equal(d.approved_current, true);
  assert.equal(A.sourceStates(db, src.id).ground_truth.draft_matches_approved, true);
  assert.equal(A.annotationStatus(db, src.id), 'approved');
});

test('2. a box marked wrong/hidden is never verified by the approval', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = content(a);
  c.keyframes.find(k => k.frame === 12).visibility = 'visible';
  c.box_verifications = [
    { segment_id: 's1', frame: 12, status: 'occluded', athlete_id: a, verified_by: 'operator', verified_at: T() },
    { segment_id: 's1', frame: 18, status: 'wrong_performer', bbox: B(0.1 + 18 / 200), athlete_id: a, verified_by: 'operator', verified_at: T() },
  ];
  A.saveDraft(db, src.id, 0, c);
  assert.equal(approvalPreview(A.getDraft(db, src.id).content).marked, 2);
  // a wrong box blocks approval until it is fixed (the operator's correction), so nothing wrong can be approved
  assert.throws(() => approve(db, src.id), e => e.code === 'BLOCKING_ITEMS');
  assert.equal(db.prepare('select count(*) n from annotation_revisions').get().n, 0);
  // remove the ✕ (operator fixed it by deleting that box): approval verifies the rest, not the hidden one
  const c2 = A.getDraft(db, src.id).content;
  c2.keyframes = c2.keyframes.filter(k => k.frame !== 18); c2.box_verifications = c2.box_verifications.filter(v => v.frame !== 18);
  A.saveDraft(db, src.id, 1, c2);
  approve(db, src.id);
  const vb = verifiedBoxes(rev(db, src.id)).map(b => b.frame);
  assert.ok(!vb.includes(12), 'hidden box not verified'); assert.ok(!vb.includes(18));
  assert.equal(vb.length, 8);
  assert.equal(latestByFrame(rev(db, src.id).box_verifications).get('s1:12').status, 'occluded');
});

test('3. a corrected box (dragged after an earlier check) is verified at its NEW geometry', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  const c = content(a);
  const old = { ...c.keyframes.find(k => k.frame === 24).bbox };
  c.box_verifications = [{ segment_id: 's1', frame: 24, status: 'verified_correct', bbox: old, athlete_id: a, verified_by: 'operator', verified_at: T() }];
  c.keyframes.find(k => k.frame === 24).verification_status = 'verified_correct';
  A.saveDraft(db, src.id, 0, c);
  // the operator drags it: the earlier check is invalidated (as the workbench records it)
  const c2 = A.getDraft(db, src.id).content, k = c2.keyframes.find(x => x.frame === 24);
  k.bbox = B(0.42); k.origin = 'manual'; k.verification_status = 'unreviewed';
  c2.box_verifications.push({ segment_id: 's1', frame: 24, status: 'unreviewed', invalidation: 'geometry_changed', athlete_id: a, verified_by: 'operator', verified_at: T() });
  A.saveDraft(db, src.id, 1, c2);
  approve(db, src.id);
  const b = verifiedBoxes(rev(db, src.id)).find(x => x.frame === 24);
  assert.deepEqual(b.bbox, B(0.42), 'the corrected geometry is what was approved');
});

test('4. partially watched: frames not watched are not verified', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a, { watched: [[0, 30]] }));
  const p = approvalPreview(A.getDraft(db, src.id).content);
  assert.equal(p.to_verify, 5); assert.equal(p.not_checked, 5); assert.equal(p.events_checked, 0);
  approve(db, src.id);
  const vb = verifiedBoxes(rev(db, src.id));
  assert.equal(vb.length, 5); assert.ok(vb.every(b => b.frame < 30));
  assert.ok(rev(db, src.id).keyframes.filter(k => k.frame >= 30).every(k => k.verification_status === 'unreviewed'));
});

test('5 + 6. edit after approval shows "changed since"; approving again adds no duplicate decisions', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a));
  approve(db, src.id);
  // approving again: nothing new, no duplicates, no new revision
  const again = approve(db, src.id);
  assert.equal(again.unchanged, true); assert.equal(again.accepted_by_exception, 0);
  assert.equal(db.prepare('select count(*) n from annotation_revisions').get().n, 1);
  assert.equal(JSON.parse(draftRow(db, src.id).content).box_verifications.length, 10);
  // an edit after approval: the approved revision is untouched; the draft no longer matches it
  const c = A.getDraft(db, src.id).content; c.segments[0].notes = 'after approval';
  A.saveDraft(db, src.id, draftRow(db, src.id).version, c);
  assert.equal(A.getDraft(db, src.id).approved_current, false);
  const st = QC.sourceCatalogState(db, A.getSource(db, src.id));
  assert.equal(st.approved, true); assert.equal(st.approved_current, false); assert.equal(st.approved_seq, 1);
  assert.equal(rev(db, src.id).segments[0].notes, '', 'the approved revision did not change');
  // approve the edit: v2, still exactly one decision per box
  approve(db, src.id);
  const r2 = rev(db, src.id);
  assert.equal(db.prepare('select max(seq) s from annotation_revisions').get().s, 2);
  assert.equal(r2.box_verifications.length, 10);
  assert.equal(new Set(r2.box_verifications.map(v => v.frame)).size, 10);
});

test('7. a failure while saving the approval leaves no approved revision and no box decisions', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a));
  assert.throws(() => approve(db, src.id, { onBeforeCommit: () => { throw new Error('power cut'); } }), /power cut/);
  assert.equal(db.prepare('select count(*) n from annotation_revisions').get().n, 0);
  const d = draftRow(db, src.id);
  assert.equal(d.version, 1); assert.equal(JSON.parse(d.content).box_verifications.length, 0);
  assert.equal(A.annotationStatus(db, src.id) === 'approved', false);
  // and it can be approved normally afterwards
  assert.equal(approve(db, src.id).accepted_by_exception, 10);
});

test('8. the training export reads the verified boxes from the approved revision (not the draft)', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a));
  approve(db, src.id);
  // a later, unapproved edit must not reach the pipeline
  const c = A.getDraft(db, src.id).content; c.keyframes.push(K('extra', 's1', 59, B(0.6)));
  A.saveDraft(db, src.id, draftRow(db, src.id).version, c);
  const ds = freezeDataset(db, { name: 'appr-test', sourceIds: [src.id] });
  const lines = exportJsonl(db, ds.id, ['train', 'validation', 'test']).trim().split('\n').map(l => JSON.parse(l));
  assert.equal(lines.length, 1);
  assert.equal(lines[0].verified_boxes.length, 10);
  assert.ok(lines[0].verified_boxes.every(b => b.athlete_id === a && b.event_type === 'wave_ride' && b.method === 'exception_review'));
  assert.ok(!lines[0].annotations.keyframes.some(k => k.id === 'extra'), 'draft-only box is not exported');
});

test('without acceptByException the approval stays as before (no box decisions are invented)', async () => {
  const { db, src } = await withSource();
  const a = A.createAthlete(db, 'A').id;
  A.saveDraft(db, src.id, 0, content(a));
  const out = approve(db, src.id, { acceptByException: false });
  assert.equal(out.accepted_by_exception, 0);
  assert.equal(verifiedBoxes(rev(db, src.id)).length, 0);
  assert.equal(draftRow(db, src.id).version, 1);
});

test('events with no performer: boxes are left unchecked, never verified', async () => {
  const { db, src } = await withSource();
  A.saveDraft(db, src.id, 0, content(null));
  const p = approvalPreview(A.getDraft(db, src.id).content);
  assert.equal(p.to_verify, 0); assert.equal(p.not_checked, 10);
});
