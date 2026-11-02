// Multi-sport catalog (spec §18.4): the six acceptance scenarios, on synthetic footage only.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';
import * as S from '../server/sports.mjs';
import * as I from '../server/imports.mjs';

async function world(n = 3) {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  for (let i = 0; i < n; i++) makeVideo(path.join(raw, `v${i}.mp4`), { seconds: 3, y: 10 + i * 20, tag: `sp${i}` });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  return { ctx, db: ctx.db, srcs: ctx.db.prepare('select * from sources order by display_name').all() };
}
const save = (db, src, build) => { const c = A.emptyContent(); build(c); return A.saveDraft(db, src.id, A.getDraft(db, src.id).version, c); };
const code = fn => { try { fn(); } catch (e) { return e.code ?? e.message; } return 'no-error'; };

test('1. registry is seeded; sources start UNCLASSIFIED (never assumed surfing); classify, filter, bulk-assign', async () => {
  const { db, srcs } = await world(3);
  assert.deepEqual(S.listSports(db).map(s => s.id).sort(), ['basketball', 'football', 'surfing', 'tennis']);
  assert.ok(srcs.every(s => s.primary_sport_id == null), 'no backfill to surfing');
  S.setSourceSport(db, srcs[0].id, 'surfing', { reason: 'confirmed' });
  const bulk = S.bulkSetSport(db, [srcs[1].id, srcs[2].id], 'football', 'bulk');
  assert.equal(bulk.updated, 2);
  const by = db.prepare('select primary_sport_id p, count(*) n from sources group by primary_sport_id order by 1').all();
  assert.deepEqual(by.map(r => `${r.p}:${Number(r.n)}`), ['football:2', 'surfing:1']);
  assert.equal(code(() => S.setSourceSport(db, srcs[0].id, 'curling')), 'NOT_FOUND', 'unknown sport rejected');
  const log = db.prepare("select detail from audit_log where action='source_sport_set' order by id").all().map(r => JSON.parse(r.detail));
  assert.deepEqual(log[0], { from: null, to: 'surfing', reason: 'confirmed', remapped: 0, incompatible_kept: 0 });
});

test('2. sport/event compatibility is enforced server-side, per segment, incl. mixed-sport sources and required attributes', async () => {
  const { db, srcs } = await world(2);
  const [a, b] = srcs;
  S.setSourceSport(db, a.id, 'football');
  assert.equal(code(() => save(db, a, c => c.segments.push(seg('s1', 5, 40, { event_type: 'wave_ride' })))), 'SPORT_EVENT_MISMATCH', 'surfing event on a football source');
  save(db, a, c => c.segments.push(seg('s1', 5, 40, { event_type: 'goal' })));
  // mixed-sport footage: a segment may override the source sport
  save(db, a, c => c.segments.push(seg('s1', 5, 40, { event_type: 'goal' }), seg('s2', 50, 80, { sport_id: 'tennis', event_type: 'serve' })));
  const d = A.getDraft(db, a.id).content;
  assert.deepEqual(d.segments.map(s => s.resolved_sport_id), ['football', 'tennis']);
  assert.equal(code(() => save(db, a, c => c.segments.push(seg('s3', 5, 40, { sport_id: 'tennis', event_type: 'goal' })))), 'SPORT_EVENT_MISMATCH');
  assert.equal(code(() => save(db, a, c => c.segments.push(seg('s3', 5, 40, { sport_id: 'nope', event_type: 'goal' })))), 'INVALID_INPUT');
  // unclassified source: only the legacy keys, so nothing is silently interpreted as a sport
  assert.equal(code(() => save(db, b, c => c.segments.push(seg('x', 5, 40, { event_type: 'goal' })))), 'SPORT_EVENT_MISMATCH');
  save(db, b, c => c.segments.push(seg('x', 5, 40, { event_type: 'wave_ride' })));
  // required attributes (configured, not coded)
  S.addEventType(db, 'tennis', { key: 'ace', label_he: 'אייס', label_en: 'Ace', required_attrs: ['serve_speed'] });
  S.setSourceSport(db, b.id, 'tennis', { acknowledgeIncompatible: true });
  assert.equal(code(() => save(db, b, c => c.segments.push(seg('y', 5, 40, { event_type: 'ace' })))), 'INVALID_INPUT', 'required attr missing');
  save(db, b, c => c.segments.push(seg('y', 5, 40, { event_type: 'ace', attrs: { serve_speed: 180 } })));
});

test('3. a new sport and event type are added by configuration only, versioned, audited, retire keeps old data valid', async () => {
  const { db, srcs } = await world(1);
  S.addSport(db, { id: 'volleyball', name_he: 'כדורעף', name_en: 'Volleyball' });
  assert.equal(S.addEventType(db, 'volleyball', { key: 'spike', label_he: 'הנחתה', label_en: 'Spike' }).taxonomy_version, 2);
  assert.equal(code(() => S.addSport(db, { id: 'volleyball', name_he: 'x', name_en: 'x' })), 'INVALID_INPUT', 'duplicate');
  assert.equal(code(() => S.addSport(db, { id: 'Bad Key', name_he: 'x', name_en: 'x' })), 'INVALID_INPUT');
  S.setSourceSport(db, srcs[0].id, 'volleyball');
  save(db, srcs[0], c => c.segments.push(seg('v', 5, 40, { event_type: 'spike' })));
  const rev = A.approve(db, srcs[0].id, { expectedVersion: A.getDraft(db, srcs[0].id).version, acknowledgeUnresolved: true }).revision;
  assert.deepEqual(JSON.parse(rev.taxonomy_versions), { volleyball: 2 }, 'taxonomy version pinned on the approved revision');
  S.setEventTypeEnabled(db, 'volleyball', 'spike', false);      // retire
  assert.equal(S.listSports(db).find(s => s.id === 'volleyball').taxonomy_version, 3);
  save(db, srcs[0], c => c.segments.push(seg('v', 5, 40, { event_type: 'spike' })));   // retired type still valid for existing annotations
  assert.equal(A.getRevision(db, rev.id).content.segments[0].event_type, 'spike');
  assert.throws(() => db.prepare("delete from sports where id='volleyball'").run(), /PROTECTED|permission|delete/i, 'sports are never deleted');
});

test('4. reclassifying a draft warns, never deletes, supports explicit remap, keeps audit; approved revisions and frozen datasets are untouched', async () => {
  const { db, srcs } = await world(1);
  const s = srcs[0];
  S.setSourceSport(db, s.id, 'surfing');
  save(db, s, c => c.segments.push(seg('a', 5, 40, { event_type: 'wave_ride' }), seg('b', 35, 55, { event_type: 'wipeout' })));
  const rev = A.approve(db, s.id, { expectedVersion: A.getDraft(db, s.id).version, acknowledgeUnresolved: true }).revision;
  const ds = D.freezeDataset(db, { name: 'frozen-before', sourceIds: [s.id] });
  save(db, s, c => c.segments.push(seg('a', 5, 40, { event_type: 'wave_ride' }), seg('b', 35, 55, { event_type: 'wipeout' }), seg('c', 60, 80, { event_type: 'paddle_out' })));
  // football has none of these keys: refused with the list, nothing changed
  let err; try { S.setSourceSport(db, s.id, 'football'); } catch (e) { err = e; }
  assert.equal(err.code, 'SPORT_INCOMPATIBLE'); assert.equal(err.incompatible.length, 3);
  assert.equal(db.prepare('select primary_sport_id p from sources where id=?').get(s.id).p, 'surfing');
  // explicit remap, then it succeeds; the segments are kept (not deleted) with their new labels
  const out = S.setSourceSport(db, s.id, 'football', { remap: { wave_ride: 'goal', wipeout: 'other', paddle_out: 'other' }, reason: 'wrong sport' });
  assert.equal(out.remapped, 3);
  const d = A.getDraft(db, s.id).content;
  assert.deepEqual(d.segments.map(x => [x.event_type, x.resolved_sport_id]), [['goal', 'football'], ['other', 'football'], ['other', 'football']]);
  // history preserved
  assert.equal(A.getRevision(db, rev.id).content.segments[0].event_type, 'wave_ride');
  assert.equal(A.getRevision(db, rev.id).content.segments[0].resolved_sport_id, 'surfing');
  assert.equal(db.prepare('select manifest from dataset_versions where id=?').get(ds.id).manifest, JSON.stringify(ds.manifest));
  const acts = db.prepare("select detail from audit_log where action='source_sport_set' order by id").all().map(r => JSON.parse(r.detail));
  assert.deepEqual(acts.map(x => [x.from, x.to]), [[null, 'surfing'], ['surfing', 'football']]);
  // explicit acknowledgement keeps incompatible segments (they then block saving until fixed)
  save(db, s, c => c.segments.push(seg('z', 5, 40, { event_type: 'goal' })));
  const ack = S.setSourceSport(db, s.id, 'tennis', { acknowledgeIncompatible: true });
  assert.equal(ack.incompatible.length, 1);
  assert.equal(A.getDraft(db, s.id).content.segments.length, 1, 'segment kept, not deleted');
  assert.equal(code(() => A.saveDraft(db, s.id, A.getDraft(db, s.id).version, A.getDraft(db, s.id).content)), 'SPORT_EVENT_MISMATCH');
});

test('5. evaluation is sport-separated: no cross-sport matching, per-sport denominators', async () => {
  const { db, srcs } = await world(1);
  const s = srcs[0];
  S.setSourceSport(db, s.id, 'football');
  save(db, s, c => { c.segments.push(seg('f', 5, 30, { event_type: 'goal' }), seg('t', 40, 70, { sport_id: 'tennis', event_type: 'serve' })); c.reviewed_ranges.push({ start_frame: 0, end_frame: s.frame_count }); });
  A.approve(db, s.id, { expectedVersion: A.getDraft(db, s.id).version, acknowledgeUnresolved: true });
  const ds = D.freezeDataset(db, { name: 'mixed', sourceIds: [s.id] });
  const pr = E.importPredictions(db, { run_id: 'r1', pipeline_version: 'v', sources: [{ source_sha256: s.sha256, events: [
    { start_frame: 5, end_frame: 30, sport_id: 'football', athlete_key: null },     // right sport, right place
    { start_frame: 40, end_frame: 70, sport_id: 'football' },                       // same time as the TENNIS GT but declared football => must NOT match it
  ] }] });
  const rep = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pr.id, params: { splits: ['train', 'validation', 'test'] } }).report;
  assert.equal(rep.by_sport.football.matched, 1);
  assert.equal(rep.by_sport.football.gt_included, 1);
  assert.equal(rep.by_sport.football.false_positives, 1, 'cross-sport prediction is a false positive for football');
  assert.equal(rep.by_sport.tennis.gt_included, 1);
  assert.equal(rep.by_sport.tennis.matched, 0);
  assert.equal(rep.by_sport.tennis.missed, 1);
  assert.equal(rep.by_sport.tennis.event_recall, 0);
  assert.equal(rep.by_sport.football.event_recall, 1);
  assert.match(rep.sport_policy, /no cross-sport/);
});

test('6. legacy surfing-style data and sport-less predictions remain valid (backward compatible)', async () => {
  const { db, srcs } = await world(1);
  const s = srcs[0];
  save(db, s, c => { c.segments.push(seg('a', 10, 40)); c.reviewed_ranges.push({ start_frame: 0, end_frame: s.frame_count }); });   // no sport anywhere
  const rev = A.approve(db, s.id, { expectedVersion: A.getDraft(db, s.id).version, acknowledgeUnresolved: true }).revision;
  assert.equal(rev.taxonomy_versions, '{}', 'no sport => nothing pinned, nothing invented');
  assert.equal(A.getRevision(db, rev.id).content.segments[0].resolved_sport_id, undefined);
  const ds = D.freezeDataset(db, { name: 'legacy', sourceIds: [s.id] });
  assert.equal(ds.manifest.members[0].taxonomy_versions, undefined);
  const pr = E.importPredictions(db, { run_id: 'r', pipeline_version: 'v', sources: [{ source_sha256: s.sha256, events: [{ start_frame: 10, end_frame: 40 }] }] });
  const rep = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pr.id, params: { splits: ['train', 'validation', 'test'] } }).report;
  assert.equal(rep.totals.matched, 1);
  assert.equal(rep.by_sport.unknown.matched, 1, 'attributed to the (unclassified) sport of the GT it matched');
});

test('pipeline predictions/v1 may declare sport per event and it reaches the evaluator', async () => {
  const { db, srcs } = await world(1);
  const s = srcs[0];
  const imp = I.importPipelinePredictions(db, { schema: 'predictions/v1', run_id: 'run-9', pipeline_commit: 'a'.repeat(40), digest: 'd', sources: [{ source_sha256: s.sha256, sport_id: 'surfing',
    events: [{ candidate_id: 'c1', decision: 'selected', start_frame: 5, end_frame: 30, event_type: 'wave_ride' }] }] });
  const payload = JSON.parse(db.prepare('select payload from pipeline_predictions where id=?').get(imp.id).payload);
  assert.equal(payload.sources[0].events[0].sport_id, 'surfing');
});
