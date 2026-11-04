// "Catalog this video again" (operator mistake): the draft is emptied, the full previous draft is kept first in the
// append-only audit log, and the reset can be undone while nothing new was saved. Each refusal asserts its reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import { newCtx, seg } from './helpers.mjs';
import * as A from '../server/annotations.mjs';

function setup() {
  const ctx = newCtx(), db = ctx.db;
  db.prepare("insert into sources(id,sha256,byte_size,display_name,frame_count,fps_num,fps_den,ingest_state,created_at) values('r1',?,10,'R.mp4',300,30,1,'ready',?)").run('c'.repeat(64), new Date().toISOString());
  const ath = A.createAthlete(db, 'גולש');
  const c = A.emptyContent();
  c.segments.push(seg('e1', 10, 90, { athlete_id: ath.id }));
  c.keyframes.push({ id: 'k1', segment_id: 'e1', frame: 20, bbox: { x: 0.1, y: 0.1, w: 0.1, h: 0.1 }, visibility: 'visible', origin: 'manual' });
  c.tracks = [{ id: 't1', athlete_id: ath.id, points: [{ frame: 20, bbox: { x: 0.1, y: 0.1, w: 0.1, h: 0.1 }, origin: 'manual' }] }];
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 300 });
  A.saveDraft(db, 'r1', 0, c);
  return { db, c };
}

test('reset empties the draft, keeps a full copy in the audit log, and can be undone exactly', () => {
  const { db, c } = setup();
  const r = A.resetDraft(db, 'r1', 1);
  assert.equal(r.version, 2);
  const d = A.getDraft(db, 'r1');
  assert.deepEqual([d.content.segments.length, d.content.keyframes.length, d.content.reviewed_ranges.length, (d.content.tracks ?? []).length], [0, 0, 0, 0]);
  const log = db.prepare("select detail from audit_log where action='draft_reset' and subject='r1'").get();
  assert.equal(JSON.parse(log.detail).previous_content.segments[0].id, 'e1', 'previous draft kept in the append-only log');
  const u = A.restoreReset(db, 'r1', 2);
  assert.equal(u.version, 3);
  const back = A.getDraft(db, 'r1').content;
  assert.equal(back.segments[0].id, 'e1'); assert.equal(back.tracks[0].points[0].frame, 20); assert.deepEqual(back.reviewed_ranges, c.reviewed_ranges);
  assert.ok(db.prepare("select 1 from audit_log where action='draft_reset_undone' and subject='r1'").get());
});

test('refusals: stale version, nothing to reset, nothing to undo, undo over newer work', () => {
  const { db } = setup();
  assert.throws(() => A.resetDraft(db, 'r1', 0), e => e.code === 'VERSION_CONFLICT');
  assert.throws(() => A.restoreReset(db, 'r1', 1), e => e.code === 'NOT_FOUND' && /אין איפוס/.test(e.message));
  A.resetDraft(db, 'r1', 1);
  assert.throws(() => A.resetDraft(db, 'r1', 2), e => e.code === 'INVALID_INPUT' && /כבר ריק/.test(e.message));
  // new work saved after the reset -> undo would overwrite it -> refused
  A.saveDraft(db, 'r1', 2, { ...A.emptyContent(), reviewed_ranges: [{ start_frame: 0, end_frame: 10 }] });
  assert.throws(() => A.restoreReset(db, 'r1', 2), e => e.code === 'VERSION_CONFLICT');
  assert.throws(() => A.restoreReset(db, 'r1', 3), e => e.code === 'VERSION_CONFLICT' && /סימונים חדשים אחרי האיפוס/.test(e.message), 'never restores over newer work');
  assert.deepEqual(A.getDraft(db, 'r1').content.reviewed_ranges, [{ start_frame: 0, end_frame: 10 }], 'the new work is intact');
  // a second reset, undone once; a second undo is refused
  A.resetDraft(db, 'r1', 3); A.restoreReset(db, 'r1', 4);
  assert.throws(() => A.restoreReset(db, 'r1', 5), e => e.code === 'NOT_FOUND');
});
