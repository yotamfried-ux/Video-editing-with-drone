// M3: drafts, concurrency, approval, immutable revisions, athlete identity.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import { ApiError } from '../server/errors.mjs';

async function withSource() {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'));
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const src = ctx.db.prepare('select * from sources').get();
  return { ctx, db: ctx.db, src };
}
const code = fn => { try { fn(); } catch (e) { return e.code ?? e.message; } return 'no-error'; };

test('draft lifecycle with optimistic concurrency', async () => {
  const { db, src } = await withSource();
  const d0 = A.getDraft(db, src.id); assert.equal(d0.version, 0);
  const c = A.emptyContent(); c.segments.push(seg('s1', 10, 50));
  assert.equal(A.saveDraft(db, src.id, 0, c).version, 1);
  assert.equal(code(() => A.saveDraft(db, src.id, 0, c)), 'VERSION_CONFLICT');
  assert.equal(A.saveDraft(db, src.id, 1, c).version, 2);
  assert.equal(A.annotationStatus(db, src.id), 'in_progress');
});

test('validation: intervals, bbox, enums, references', async () => {
  const { db, src } = await withSource();
  const mk = f => { const c = A.emptyContent(); f(c); return c; };
  const tryS = c => code(() => A.saveDraft(db, src.id, A.getDraft(db, src.id).version, c));
  assert.equal(tryS(mk(c => c.segments.push(seg('a', 50, 50)))), 'INVALID_INTERVAL');
  assert.equal(tryS(mk(c => c.segments.push(seg('a', 60, 50)))), 'INVALID_INTERVAL');
  assert.equal(tryS(mk(c => c.segments.push(seg('a', -1, 5)))), 'INVALID_INTERVAL');
  assert.equal(tryS(mk(c => c.segments.push(seg('a', 0, src.frame_count + 1)))), 'INVALID_INTERVAL');
  assert.equal(tryS(mk(c => c.segments.push(seg('a', 0, 5, { decision: 'maybe' })))), 'INVALID_INPUT');
  assert.equal(tryS(mk(c => c.segments.push(seg('a', 0, 5, { athlete_id: 'nope' })))), 'INVALID_INPUT');
  const bb = b => mk(c => { c.segments.push(seg('a', 0, 20)); c.keyframes.push(kf('k', 'a', 5, b)); });
  assert.equal(tryS(bb({ x: 0.9, y: 0.1, w: 0.2, h: 0.1 })), 'INVALID_BBOX');
  assert.equal(tryS(bb({ x: 0.1, y: 0.1, w: 0, h: 0.1 })), 'INVALID_BBOX');
  assert.equal(tryS(bb({ x: -0.1, y: 0.1, w: 0.1, h: 0.1 })), 'INVALID_BBOX');
  assert.equal(tryS(bb({ x: 0.1, y: 0.1, w: NaN, h: 0.1 })), 'INVALID_BBOX');
  assert.equal(tryS(mk(c => { c.segments.push(seg('a', 0, 20)); c.keyframes.push(kf('k', 'a', 25, { x: .1, y: .1, w: .1, h: .1 })); })), 'INVALID_INTERVAL');
  assert.equal(tryS(bb({ x: 0.1, y: 0.1, w: 0.1, h: 0.1 })), 'no-error');
});

test('approval creates immutable, chained revisions; reload keeps exact frames', async () => {
  const { db, src } = await withSource();
  const ath = A.createAthlete(db, 'גולש 1');
  let c = A.emptyContent();
  c.segments.push(seg('w1', 18 * 3 + 1, 28 * 3 + 2, { athlete_id: ath.id }));
  c.keyframes.push(kf('k1', 'w1', 55, { x: 0.25, y: 0.3, w: 0.125, h: 0.222 }));
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 120 });
  A.saveDraft(db, src.id, 0, c);
  const r1 = A.approve(db, src.id, { expectedVersion: 1, reason: 'first pass' });
  assert.equal(r1.revision.seq, 1); assert.equal(A.annotationStatus(db, src.id), 'approved');
  // idempotent when nothing changed
  assert.equal(A.approve(db, src.id, { expectedVersion: 1 }).unchanged, true);
  // edit -> in_progress, approve -> revision 2 chained to 1
  c = A.getDraft(db, src.id).content; c.segments[0].end_frame += 3; A.saveDraft(db, src.id, 1, c);
  assert.equal(A.annotationStatus(db, src.id), 'in_progress');
  const r2 = A.approve(db, src.id, { expectedVersion: 2 });
  assert.equal(r2.revision.seq, 2); assert.equal(r2.revision.parent_revision_id, r1.revision.id);
  // revision 1 is untouched and still returns the exact original frames
  const old = A.getRevision(db, r1.revision.id);
  assert.equal(old.content.segments[0].start_frame, 55); assert.equal(old.content.segments[0].end_frame, 86);
  assert.throws(() => db.prepare('update annotation_revisions set content=? where id=?').run('{}', r1.revision.id), /IMMUTABLE/);
  assert.throws(() => db.prepare('delete from annotation_revisions where id=?').run(r1.revision.id), /IMMUTABLE/);
  assert.equal(A.listRevisions(db, src.id).length, 2);
});

test('approval blocks on stale version and on unresolved items without explicit acknowledgement', async () => {
  const { db, src } = await withSource();
  const c = A.emptyContent(); c.segments.push(seg('u', 5, 30, { decision: 'uncertain' }), seg('i', 40, 60)); // include with unknown athlete
  A.saveDraft(db, src.id, 0, c);
  assert.equal(A.annotationStatus(db, src.id), 'needs_review');
  assert.equal(code(() => A.approve(db, src.id, { expectedVersion: 0 })), 'VERSION_CONFLICT');
  let err; try { A.approve(db, src.id, { expectedVersion: 1 }); } catch (e) { err = e; }
  assert.equal(err.code, 'UNRESOLVED_ITEMS'); assert.deepEqual(err.unresolved, { uncertain_segments: 1, unknown_athlete_included: 1 });
  const ok = A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true });
  assert.equal(ok.revision.seq, 1);
});

test('overlapping events and multiple surfers are supported; coverage counts reviewed frames only', async () => {
  const { db, src } = await withSource();
  const a1 = A.createAthlete(db, 'A'), a2 = A.createAthlete(db, 'B');
  const c = A.emptyContent();
  c.segments.push(seg('x', 10, 60, { athlete_id: a1.id }), seg('y', 40, 90, { athlete_id: a2.id }), seg('z', 45, 55, { athlete_id: a1.id, decision: 'exclude', event_type: 'failed_takeoff', reason_code: 'failed_takeoff' }));
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 30 }, { start_frame: 20, end_frame: 60 });
  A.saveDraft(db, src.id, 0, c);
  assert.equal(A.reviewedCoverage(c, src.frame_count).reviewed_frames, 60);
  const ap = A.listAthletes(db);
  assert.equal(ap.find(a => a.id === a1.id).appearances.length, 1);
  A.setAppearanceFlags(db, a1.id, src.id, { uncertain: 1 });
  assert.equal(A.listAthletes(db).find(a => a.id === a1.id).appearances[0].uncertain, 1);
});

test('revisions survive a restart (fresh connection to the same home)', async () => {
  const { ctx, db, src } = await withSource();
  const c = A.emptyContent(); c.segments.push(seg('s', 7, 77)); A.saveDraft(db, src.id, 0, c);
  const rev = A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true }).revision;
  const { createContext } = await import('../server/context.mjs');
  const again = createContext(ctx.home, { dbUrl: ctx.dbUrl });
  const r = A.getRevision(again.db, rev.id);
  assert.equal(r.content.segments[0].start_frame, 7); assert.equal(r.content.segments[0].end_frame, 77);
});

test('approval refused when archive is not verified', async () => {
  const { db, src } = await withSource();
  const c = A.emptyContent(); c.segments.push(seg('s', 1, 9)); A.saveDraft(db, src.id, 0, c);
  db.prepare("update sources set ingest_state='archive_error' where id=?").run(src.id);
  assert.equal(code(() => A.approve(db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true })), 'ARCHIVE_UNVERIFIED');
});
void ApiError;
