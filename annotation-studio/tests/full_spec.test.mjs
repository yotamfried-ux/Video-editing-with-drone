// FULL_SPEC normative addendum v1: independent annotation sets (§2), event-scoped primary (§3), physical-action lineage (§4),
// person merge/split lineage (§6), deterministic matching (§8), Jaccard agreement (§9), evaluation identity (§10), freeze (§11).
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as Sets from '../server/sets.mjs';
import * as Lin from '../server/lineage.mjs';
import * as D from '../server/datasets.mjs';
import * as E from '../server/evaluate.mjs';

async function world(n = 2) {
  const ctx = newCtx(); const raw = path.join(tmp('ops-'), 'raw');
  for (let i = 0; i < n; i++) makeVideo(path.join(raw, `v${i}.mp4`), { seconds: 3, y: 20 + i * 30, tag: `fs${i}` });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  return { ctx, db: ctx.db, srcs: ctx.db.prepare('select * from sources order by display_name').all() };
}
const code = c => e => e.code === c;
function approvePrimary(db, src, segs) {
  const c = A.emptyContent(); c.segments.push(...segs);
  const v = A.getDraft(db, src.id).version;
  A.saveDraft(db, src.id, v, c); return A.approve(db, src.id, { expectedVersion: v + 1, acknowledgeUnresolved: true });
}

test('§2 sets: a new assignment starts EMPTY (never sees the primary), OCC, completion, immutability after submit', async () => {
  const { db, srcs: [s0] } = await world(1);
  const ath = A.createAthlete(db, 'P').id;
  approvePrimary(db, s0, [seg('p1', 10, 50, { athlete_id: ath })]);
  const set = Sets.createSet(db, { purpose: 'delayed_blind_reannotation', annotator_id: 'ann-2' });
  assert.equal(set.status, 'active');
  Sets.addAssignments(db, set.id, [s0.id]);
  const d = Sets.getSetDraft(db, set.id, s0.id);
  assert.deepEqual(d.content.segments, [], 'independent stream starts empty');
  assert.equal(d.queue_status, 'unlabeled');
  // Isolation: the primary's approved revision is not readable from this unsubmitted set.
  assert.throws(() => Sets.readForComparison(db, 'primary', s0.id, { viewerSetId: set.id }), code('SET_ISOLATION'));
  const c = A.emptyContent(); c.segments.push(seg('b1', 12, 52, { athlete_id: null, decision: 'include', usability: 'usable', primary_status: 'uncertain_primary' }));
  assert.equal(Sets.saveSetDraft(db, set.id, s0.id, { expected_version: 0, content: c, playback_position_ms: 1200 }).version, 1);
  assert.throws(() => Sets.saveSetDraft(db, set.id, s0.id, { expected_version: 0, content: c }), code('VERSION_CONFLICT'));
  assert.equal(Sets.getSetDraft(db, set.id, s0.id).playback_position_ms, 1200, 'resume position is assignment-scoped');
  assert.equal(A.getDraft(db, s0.id).content.segments[0].id, 'p1', 'primary untouched');
  assert.throws(() => Sets.submitSet(db, set.id), /טרם הושלמו/);
  Sets.completeAssignment(db, set.id, s0.id, { expected_version: 1 });
  assert.throws(() => Sets.saveSetDraft(db, set.id, s0.id, { expected_version: 1, content: c }), code('SET_IMMUTABLE'));
  assert.equal(Sets.submitSet(db, set.id).status, 'submitted');
  assert.throws(() => Sets.addAssignments(db, set.id, [s0.id]), code('SET_IMMUTABLE'));
  assert.throws(() => db.prepare('update set_revisions set content=?').run('{}'), /IMMUTABLE/);
  // after submission, comparison is allowed
  assert.equal(Sets.readForComparison(db, 'primary', s0.id, { viewerSetId: set.id }).content.segments[0].id, 'p1');
});

test('§9 Jaccard: both-empty = 1, one-empty = 0, unknown codes invalid; exact-set and per-label counts', () => {
  assert.equal(Sets.jaccard([], []).value, 1);
  assert.equal(Sets.jaccard(['occlusion'], []).value, 0);
  assert.equal(Sets.jaccard(['occlusion', 'missing_takeoff'], ['occlusion']).value, 0.5);
  assert.equal(Sets.jaccard(['occlusion', 'occlusion'], ['occlusion']).value, 1, 'deduplicated');
  assert.equal(Sets.jaccard(['made_up'], ['occlusion']).invalid, true);
});

test('§8 matching: one-to-one, IoU then boundary error then ids; incompatible types and sub-threshold never match; invalid config inconclusive', () => {
  const g = [{ id: 'g1', start_frame: 0, end_frame: 100, event_type: 'wave_ride' }];
  // p1 and p2 have identical IoU with g1; p2 has smaller combined boundary error -> p2 wins
  const p = [{ id: 'p1', start_frame: 10, end_frame: 110, event_type: 'wave_ride' }, { id: 'p2', start_frame: 0, end_frame: 90, event_type: 'wave_ride' },
    { id: 'p3', start_frame: 0, end_frame: 100, event_type: 'wipeout' }, { id: 'p4', start_frame: 95, end_frame: 300, event_type: 'wave_ride' }];
  const iou = (a, b) => (Math.min(a.end_frame, b.end_frame) - Math.max(a.start_frame, b.start_frame)) / (Math.max(a.end_frame, b.end_frame) - Math.min(a.start_frame, b.start_frame));
  assert.equal(iou(g[0], p[0]).toFixed(4), (90 / 110).toFixed(4)); assert.equal(iou(g[0], p[1]), 0.9);
  const m = Sets.matchEvents(g, p, { min_temporal_iou: 0.3 });
  assert.equal(m.matched.length, 1); assert.equal(m.matched[0].b.id, 'p2');
  assert.deepEqual(m.only_b.map(x => x.id).sort(), ['p1', 'p3', 'p4']);
  const tie = Sets.matchEvents([{ id: 'g', start_frame: 0, end_frame: 100, event_type: 'x' }], [{ id: 'b', start_frame: 0, end_frame: 90, event_type: 'x' }, { id: 'a', start_frame: 10, end_frame: 100, event_type: 'x' }], { min_temporal_iou: 0.3 });
  assert.equal(tie.matched[0].b.id, 'a', 'equal IoU and error -> lexical prediction id');
  assert.equal(Sets.matchEvents(g, p, { min_temporal_iou: 0 }).inconclusive, true);
});

test('§2.3 identities are compared as partitions across set-scoped namespaces; blocking disagreements are explicit', () => {
  const mk = (ids, ath, extra = {}) => ({ schema: 1, keyframes: [], reviewed_ranges: [], segments: ids.map((id, i) => ({ id, start_frame: i * 100, end_frame: i * 100 + 80, event_type: 'wave_ride', decision: 'include', usability: 'usable', reason_codes: [], athlete_id: ath[i], ...extra })) });
  // Set A calls the people X,X,Y; set B calls them Q,Q,R — different codes, same partition -> full identity agreement
  const r1 = Sets.compareContents(mk(['a1', 'a2', 'a3'], ['X', 'X', 'Y']), mk(['b1', 'b2', 'b3'], ['Q', 'Q', 'R']));
  assert.equal(r1.identity_pair_agreement, 1); assert.equal(r1.blocking_disagreements.length, 0);
  const r2 = Sets.compareContents(mk(['a1', 'a2', 'a3'], ['X', 'X', 'Y']), mk(['b1', 'b2', 'b3'], ['Q', 'R', 'R']));
  assert.ok(r2.identity_pair_agreement < 1);
  assert.ok(r2.blocking_disagreements.some(b => b.type === 'identity_partition_disagreement'));
  const r3 = Sets.compareContents(mk(['a1'], ['X'], { usability: 'usable' }), mk(['b1'], ['Q'], { usability: 'unusable', reason_codes: ['occlusion'] }));
  assert.ok(r3.blocking_disagreements.some(b => b.type === 'usability_disagreement'));
  assert.equal(r3.reason_jaccard_mean, 0);
});

test('§2/§11 adjudication: needs >=2 submitted sets, reads contributors, never mutates them; freeze blocked until adjudicated', async () => {
  const { db, srcs: [s0] } = await world(1);
  const ath = A.createAthlete(db, 'P').id;
  approvePrimary(db, s0, [seg('p1', 10, 50, { athlete_id: ath, usability: 'usable' })]);
  const qa = Sets.createSet(db, { purpose: 'independent_qa', annotator_id: 'qa-1' });
  Sets.addAssignments(db, qa.id, [s0.id]);
  const c = A.emptyContent(); c.segments.push(seg('q1', 10, 50, { athlete_id: ath, decision: 'include', usability: 'unusable', reason_codes: ['occlusion'] }));
  Sets.saveSetDraft(db, qa.id, s0.id, { expected_version: 0, content: c });
  assert.throws(() => Sets.createSet(db, { purpose: 'adjudication', annotator_id: 'adj', contributing_set_ids: ['primary', qa.id] }), code('SET_NOT_SUBMITTED'));
  assert.throws(() => Sets.agreementReport(db, 'primary', qa.id), code('SET_NOT_SUBMITTED'));
  Sets.completeAssignment(db, qa.id, s0.id, { expected_version: 1 }); Sets.submitSet(db, qa.id);
  const rep = Sets.agreementReport(db, 'primary', qa.id);
  assert.equal(rep.sources, 1); assert.ok(rep.blocking_total >= 1); assert.match(rep.digest, /^[0-9a-f]{64}$/);
  assert.throws(() => D.freezeDataset(db, { name: 'blocked', sourceIds: [s0.id] }), code('BLOCKING_DISAGREEMENT'));
  const adj = Sets.createSet(db, { purpose: 'adjudication', annotator_id: 'adj', contributing_set_ids: ['primary', qa.id] });
  assert.equal(adj.status, 'adjudicating');
  assert.ok(Sets.readForComparison(db, qa.id, s0.id, { viewerSetId: adj.id }), 'adjudicator reads the contributing set');
  Sets.addAssignments(db, adj.id, [s0.id]);
  const ac = A.emptyContent(); ac.segments.push(seg('j1', 10, 50, { athlete_id: ath, usability: 'partially_usable', reason_codes: ['occlusion'] }));
  Sets.saveSetDraft(db, adj.id, s0.id, { expected_version: 0, content: ac });
  Sets.completeAssignment(db, adj.id, s0.id, { expected_version: 1 });
  assert.equal(Sets.submitSet(db, adj.id).status, 'accepted');
  assert.equal(Sets.readForComparison(db, qa.id, s0.id).content.segments[0].usability, 'unusable', 'contributing set unchanged');
  const ds = D.freezeDataset(db, { name: 'adjudicated', sourceIds: [s0.id] });
  assert.deepEqual(ds.manifest.annotation_sets.independent_sets.sort(), [qa.id, adj.id].sort());
});

test('§6 person lineage: merge many->one, split one->many, retire, no cycles, append-only, frozen graph by relation ids', async () => {
  const { db } = await world(1);
  const [a, b, c, d, e] = ['a', 'b', 'c', 'd', 'e'].map(l => A.createAthlete(db, l).id);
  const r1 = Lin.addPersonRelation(db, { relation_type: 'merge', from_person_id: a, to_person_id: c, reason_code: 'same_person' });
  Lin.addPersonRelation(db, { relation_type: 'merge', from_person_id: b, to_person_id: c, reason_code: 'same_person' });
  assert.deepEqual(Lin.resolvePerson(db, a).successors, [c]); assert.deepEqual(Lin.resolvePerson(db, b).successors, [c]);
  Lin.addPersonRelation(db, { relation_type: 'split', from_person_id: c, to_person_id: d, reason_code: 'two_people' });
  Lin.addPersonRelation(db, { relation_type: 'split', from_person_id: c, to_person_id: e, reason_code: 'two_people' });
  assert.deepEqual(Lin.resolvePerson(db, a).successors, [d, e].sort());
  assert.deepEqual(Lin.resolvePerson(db, a, { relationIds: [r1.id] }).successors, [c], 'historical graph reproducible from exact relation ids');
  assert.throws(() => Lin.addPersonRelation(db, { relation_type: 'merge', from_person_id: d, to_person_id: a, reason_code: 'x' }), /מעגל/);
  assert.throws(() => Lin.addPersonRelation(db, { relation_type: 'merge', from_person_id: d, to_person_id: d, reason_code: 'x' }), code('INVALID_INPUT'));
  Lin.addPersonRelation(db, { relation_type: 'retire', from_person_id: e, reason_code: 'not_a_person' });
  assert.equal(Lin.resolvePerson(db, e).retired, true);
  assert.throws(() => db.prepare('delete from person_lineage_relations').run(), /IMMUTABLE/);
  assert.equal(Lin.personLineage(db).relations.length, 5);
});

test('§4 physical actions: same wave in two videos, one event in one active action, merge/split append-only, coverage, frozen manifest', async () => {
  const { db, srcs: [s0, s1] } = await world(2);
  const ath = A.createAthlete(db, 'P').id;
  approvePrimary(db, s0, [seg('e0', 10, 60, { athlete_id: ath })]);
  approvePrimary(db, s1, [seg('e1', 5, 55, { athlete_id: ath }), seg('e2', 60, 80, { athlete_id: ath })]);
  const wave = Lin.createPhysicalAction(db, { action_type: 'wave_ride', primary_person_id: ath });
  Lin.linkOccurrence(db, wave.id, { source_id: s0.id, segment_id: 'e0', occurrence_role: 'canonical_view' });
  const o2 = Lin.linkOccurrence(db, wave.id, { source_id: s1.id, segment_id: 'e1', occurrence_role: 'duplicate_view' });
  assert.ok(o2.evidence_revision_id, 'evidence bound to the approved revision');
  const other = Lin.createPhysicalAction(db, { action_type: 'wave_ride' });
  assert.throws(() => Lin.linkOccurrence(db, other.id, { source_id: s1.id, segment_id: 'e1' }), /פעולה פיזית אחרת/);
  assert.throws(() => Lin.linkOccurrence(db, wave.id, { source_id: s1.id, segment_id: 'nope' }), code('NOT_FOUND'));
  Lin.linkOccurrence(db, other.id, { source_id: s1.id, segment_id: 'e2' });
  let cov = Lin.actionCoverage(db);
  assert.deepEqual([cov.physical_actions, cov.occurrences, cov.multi_view_actions, cov.duplicate_views], [2, 3, 1, 1]);
  const merged = Lin.mergeActions(db, [wave.id, other.id], { reason: 'same set of waves' });
  assert.equal(merged.occurrences.length, 3);
  assert.equal(Lin.getPhysicalAction(db, wave.id).lineage_state, 'merged');
  const parts = Lin.splitAction(db, merged.id, [[merged.occurrences[0].id, merged.occurrences[1].id], [merged.occurrences[2].id]], { reason: 'e2 is a different wave' });
  assert.equal(parts.length, 2); assert.equal(Lin.getPhysicalAction(db, merged.id).lineage_state, 'split');
  assert.equal(Lin.getPhysicalAction(db, merged.id).history.length, 2, 'full state history kept');
  cov = Lin.actionCoverage(db); assert.equal(cov.physical_actions, 2); assert.equal(cov.occurrences, 3);
  Lin.setActionState(db, parts[0].id, 'accepted');
  const ds = D.freezeDataset(db, { name: 'with-lineage', sourceIds: [s0.id, s1.id] });
  assert.equal(ds.manifest.lineage.physical_actions.length, 2);
  assert.ok(ds.manifest.lineage.physical_actions.find(a => a.lineage_state === 'accepted').occurrences.length === 2);
  assert.throws(() => db.prepare('update physical_actions set action_type=?').run('x'), /IMMUTABLE/);
});

test('§3 event-scoped primary: explicit no/uncertain primary; usable events need one; item primary is derived, never forced', async () => {
  const { db, srcs: [s0] } = await world(1);
  const a = A.createAthlete(db, 'A').id, b = A.createAthlete(db, 'B').id;
  const c = A.emptyContent();
  c.segments.push(seg('x', 0, 30, { athlete_id: null, usability: 'usable' }));
  A.saveDraft(db, s0.id, 0, c);
  assert.equal(A.unresolved(A.getDraft(db, s0.id).content, s0).usable_without_primary, 1);
  c.segments[0].primary_status = 'no_primary_action';
  A.saveDraft(db, s0.id, 1, c);
  assert.equal(A.unresolved(A.getDraft(db, s0.id).content, s0).usable_without_primary, 0);
  c.segments[0].primary_status = 'person';
  assert.throws(() => A.saveDraft(db, s0.id, 2, c), code('INVALID_INPUT'));
  c.segments[0] = { ...c.segments[0], athlete_id: a, primary_status: 'person' };
  c.segments.push(seg('y', 40, 70, { athlete_id: b, primary_status: 'person' }));
  A.saveDraft(db, s0.id, 2, c);
  assert.equal(A.sourceStates(db, s0.id).item_primary.state, 'multiple_event_owners');
  c.segments[1].athlete_id = a; A.saveDraft(db, s0.id, 3, c);
  assert.deepEqual(A.sourceStates(db, s0.id).item_primary, { state: 'single', athlete_id: a });
});

test('§10 evaluation identity: identical tuple -> same run (idempotent); any component change -> new identity; invalid config refused', async () => {
  const { db, srcs: [s0] } = await world(1);
  approvePrimary(db, s0, [seg('g', 10, 60, { athlete_id: A.createAthlete(db, 'P').id })]);
  const ds = D.freezeDataset(db, { name: 'e', sourceIds: [s0.id], policy: { seed: 'x', ratios: { train: 0, validation: 0, test: 1 } } });
  const pred = E.importPredictions(db, { run_id: 'r1', pipeline_version: 'p@1', sources: [{ source_sha256: s0.sha256, events: [{ start_frame: 12, end_frame: 58, athlete_key: 'T' }] }] });
  const r1 = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pred.id });
  const r2 = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pred.id });
  assert.equal(r2.id, r1.id); assert.equal(r2.idempotent_replay, true);
  assert.equal(db.prepare('select count(*) n from evaluation_runs').get().n, 1);
  const r3 = E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pred.id, params: { iou_threshold: 0.7 } });
  assert.notEqual(r3.id, r1.id);
  assert.equal(r1.report.comparison_identity.event_matching_config_version, E.MATCHING_VERSION);
  assert.throws(() => E.runEvaluation(db, { dataset_id: ds.id, prediction_id: pred.id, params: { iou_threshold: 0 } }), /inconclusive/);
});

test('backup/restore carries annotation sets and lineage; integrity audit covers set revisions', async () => {
  const { db, srcs: [s0, s1] } = await world(2);
  const ath = A.createAthlete(db, 'P').id;
  approvePrimary(db, s0, [seg('e0', 10, 60, { athlete_id: ath })]);
  approvePrimary(db, s1, [seg('e1', 5, 55, { athlete_id: ath })]);
  const set = Sets.createSet(db, { purpose: 'independent_qa', annotator_id: 'qa' }); Sets.addAssignments(db, set.id, [s0.id]);
  const c = A.emptyContent(); c.segments.push(seg('q', 10, 60, { athlete_id: ath })); Sets.saveSetDraft(db, set.id, s0.id, { expected_version: 0, content: c });
  Sets.completeAssignment(db, set.id, s0.id, { expected_version: 1 });
  const act = Lin.createPhysicalAction(db, { action_type: 'wave_ride' });
  Lin.linkOccurrence(db, act.id, { source_id: s0.id, segment_id: 'e0' }); Lin.linkOccurrence(db, act.id, { source_id: s1.id, segment_id: 'e1' });
  const b2 = A.createAthlete(db, 'P2').id; Lin.addPersonRelation(db, { relation_type: 'merge', from_person_id: b2, to_person_id: ath, reason_code: 'same' });
  const { exportBackup, restoreBackup, verifyIntegrity } = await import('../server/backup.mjs');
  const bk = exportBackup(db);
  const fresh = newCtx();
  restoreBackup(fresh.db, bk);
  assert.equal(Sets.getSetDraft(fresh.db, set.id, s0.id).queue_status, 'completed');
  assert.equal(Lin.getPhysicalAction(fresh.db, act.id).occurrences.length, 2);
  assert.deepEqual(Lin.resolvePerson(fresh.db, b2).successors, [ath]);
  assert.equal(verifyIntegrity(fresh.db).ok, true);
});

test('§18 suggested sport needs confirmation; mixed-sport membership; stratified splits per sport; annotated-context metrics', async () => {
  const { db, srcs } = await world(4);
  const Sp = await import('../server/sports.mjs');
  Sp.suggestSourceSport(db, srcs[0].id, { sport_id: 'surfing', source: 'metadata' });
  assert.equal(db.prepare('select primary_sport_id from sources where id=?').get(srcs[0].id).primary_sport_id, null, 'a suggestion never classifies');
  Sp.confirmSuggestedSport(db, srcs[0].id);
  assert.equal(db.prepare('select primary_sport_id, suggested_sport_id from sources where id=?').get(srcs[0].id).primary_sport_id, 'surfing');
  assert.throws(() => Sp.confirmSuggestedSport(db, srcs[0].id), code('INVALID_INPUT'));
  assert.deepEqual(Sp.addSourceSport(db, srcs[0].id, 'football').all, ['football', 'surfing']);
  for (const s of srcs.slice(1)) Sp.setSourceSport(db, s.id, s === srcs[3] ? 'football' : 'surfing', { reason: 't' });
  const ath = A.createAthlete(db, 'P').id;
  for (const s of srcs) approvePrimary(db, s, [seg(`e-${s.id.slice(0, 4)}`, 10, 60, { athlete_id: ath, event_type: s === srcs[3] ? 'goal' : 'wave_ride', key_moments: s === srcs[3] ? {} : { takeoff_frame: 12, landing_frame: 58 } })]);
  const ds = D.freezeDataset(db, { name: 'strat', sourceIds: srcs.map(s => s.id), policy: { seed: 's', ratios: { train: 0.5, validation: 0, test: 0.5 }, stratify_by_sport: true } });
  assert.deepEqual(Object.keys(ds.manifest.sport_strata).sort(), ['football', 'surfing']);
  assert.ok(ds.manifest.sport_strata.surfing.train >= 1 && ds.manifest.sport_strata.surfing.test >= 1, JSON.stringify(ds.manifest.sport_strata));
  const ds2 = D.freezeDataset(db, { name: 'all-test', sourceIds: srcs.map(s => s.id), policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
  const pred = E.importPredictions(db, { run_id: 'r', pipeline_version: 'p', sources: srcs.map(s => ({ source_sha256: s.sha256, events: [{ start_frame: 10, end_frame: 60, athlete_key: 'T' }] })) });
  const r = E.runEvaluation(db, { dataset_id: ds2.id, prediction_id: pred.id, params: { splits: ['train', 'validation', 'test'] } });
  assert.equal(r.report.by_sport.surfing.complete_wave_recall, 1);
  assert.equal(r.report.by_sport.surfing.complete_wave_annotated, 3);
});

test('§7 raw-only boundary and §5 canonical binding: the workbench never loads pipeline outputs; media is resolved from server ids', async () => {
  const { readFileSync } = await import('node:fs');
  const ann = readFileSync(new URL('../web/js/annotate.js', import.meta.url), 'utf8');
  for (const forbidden of ['/api/predictions', '/api/outputs', '/api/evaluations', '/api/editing', '/api/imports', 'edl']) {
    assert.ok(!ann.includes(forbidden), `annotation workbench must not consult ${forbidden}`);
  }
  const app = readFileSync(new URL('../server/app.mjs', import.meta.url), 'utf8');
  // media/cloud routes take only opaque server-issued ids; no client-supplied storage key is ever accepted
  assert.ok(!/searchParams\.get\(['"](key|raw_key|storage_key|path)['"]\)/.test(app));
});
