// Revisioned identity lineage (addendum §6) and cross-video physical-action lineage (addendum §4).
// Everything here is append-only (database triggers): merges/splits/retirements add rows; nothing is rewritten.
import { randomUUID } from 'node:crypto';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { latestRevision, getDraft } from './annotations.mjs';

// ---------------- persons (§6) ----------------
export const RELATIONS = ['merge', 'split', 'equivalent', 'retire'];
const athlete = (db, id) => { if (!id || !db.prepare('select 1 from athletes where id=?').get(id)) throw new ApiError('NOT_FOUND', `גולש לא קיים: ${id}`); };

/**
 * merge:  several predecessors -> one successor  (call once per predecessor with the same to_person_id)
 * split:  one predecessor -> several successors   (call once per successor)
 * equivalent: same person, both stay valid; retire: person no longer used (no successor)
 */
export function addPersonRelation(db, { set_id = 'primary', relation_type, from_person_id, to_person_id = null, reason_code, contributing_revision_id = null, created_by = 'operator' } = {}) {
  if (!RELATIONS.includes(relation_type)) throw new ApiError('INVALID_INPUT', 'סוג קשר לא תקין');
  if (!reason_code || !String(reason_code).trim()) throw new ApiError('INVALID_INPUT', 'חובה לציין סיבה');
  athlete(db, from_person_id);
  if (relation_type === 'retire') { if (to_person_id) throw new ApiError('INVALID_INPUT', 'retire אינו מצביע על יורש'); }
  else { athlete(db, to_person_id); if (to_person_id === from_person_id) throw new ApiError('INVALID_INPUT', 'קשר עצמי אינו חוקי'); }
  if (!db.prepare('select 1 from annotation_sets where id=?').get(set_id)) throw new ApiError('NOT_FOUND', 'סט לא קיים');
  // No cycles through succession edges.
  if (['merge', 'split'].includes(relation_type) && resolvePerson(db, to_person_id).successors.includes(from_person_id)) {
    throw new ApiError('INVALID_INPUT', 'הקשר יוצר מעגל בשושלת הזהויות');
  }
  const id = randomUUID();
  db.prepare('insert into person_lineage_relations(id,set_id,relation_type,from_person_id,to_person_id,contributing_revision_id,reason_code,created_by,created_at) values(?,?,?,?,?,?,?,?,?)')
    .run(id, set_id, relation_type, from_person_id, to_person_id, contributing_revision_id, String(reason_code).trim(), created_by, now());
  audit(db, created_by, 'person_lineage_relation', id, { relation_type, from_person_id, to_person_id, set_id });
  return db.prepare('select * from person_lineage_relations where id=?').get(id);
}

/** Current identities a historical person maps to, using only the given relation ids (a frozen graph) or all. */
export function resolvePerson(db, personId, { relationIds = null, setId = 'primary' } = {}) {
  const rel = db.prepare('select * from person_lineage_relations where set_id=? order by created_at, id').all(setId)
    .filter(r => !relationIds || relationIds.includes(r.id));
  const out = new Map(); let retired = false;
  const seen = new Set();
  const walk = p => {
    if (seen.has(p)) return; seen.add(p);
    const next = rel.filter(r => r.from_person_id === p && (r.relation_type === 'merge' || r.relation_type === 'split'));
    if (rel.some(r => r.from_person_id === p && r.relation_type === 'retire')) { retired = true; return; }
    if (!next.length) { out.set(p, true); return; }
    for (const r of next) walk(r.to_person_id);
  };
  walk(personId);
  const equivalents = rel.filter(r => r.relation_type === 'equivalent' && [...out.keys()].some(k => k === r.from_person_id || k === r.to_person_id))
    .flatMap(r => [r.from_person_id, r.to_person_id]);
  return { person_id: personId, successors: [...out.keys()].sort(), equivalent_to: [...new Set(equivalents)].filter(x => !out.has(x)).sort(), retired };
}

export function personLineage(db, { setId = 'primary' } = {}) {
  const relations = db.prepare('select * from person_lineage_relations where set_id=? order by created_at, id').all(setId);
  return { set_id: setId, relations, mapping: db.prepare('select id from athletes order by id').all().map(a => resolvePerson(db, a.id, { setId })) };
}

// ---------------- physical actions (§4) ----------------
export const ROLES = ['canonical_view', 'duplicate_view', 'supplementary_view', 'uncertain'];
const actionState = (db, id) => db.prepare('select lineage_state from physical_action_states where physical_action_id=? order by id desc limit 1').get(id)?.lineage_state;
const ACTIVE = new Set(['provisional', 'accepted']);
const activeOccurrences = (db, actionId) => db.prepare(`select o.* from action_occurrences o where o.physical_action_id=?
  and not exists (select 1 from action_occurrence_retirements r where r.occurrence_id=o.id) order by o.created_at, o.id`).all(actionId);
function pushState(db, id, lineage_state, { related = [], reason = null, actor = 'operator' } = {}) {
  db.prepare('insert into physical_action_states(physical_action_id,lineage_state,related_action_ids,reason,actor,at) values(?,?,?,?,?,?)')
    .run(id, lineage_state, JSON.stringify(related), reason, actor, now());
}

export function createPhysicalAction(db, { sport_id = null, action_type, primary_person_id = null, actor = 'operator' } = {}) {
  if (!action_type) throw new ApiError('INVALID_INPUT', 'חובה לציין סוג פעולה');
  if (primary_person_id) athlete(db, primary_person_id);
  const id = randomUUID();
  return tx(db, () => {
    db.prepare('insert into physical_actions(id,sport_id,action_type,primary_person_id,created_at) values(?,?,?,?,?)').run(id, sport_id, action_type, primary_person_id, now());
    pushState(db, id, 'provisional', { actor });
    audit(db, actor, 'physical_action_created', id, { action_type });
    return getPhysicalAction(db, id);
  });
}

export function getPhysicalAction(db, id) {
  const a = db.prepare('select * from physical_actions where id=?').get(id);
  if (!a) throw new ApiError('NOT_FOUND', 'פעולה פיזית לא נמצאה');
  return { ...a, lineage_state: actionState(db, id), history: db.prepare('select * from physical_action_states where physical_action_id=? order by id').all(id).map(s => ({ ...s, related_action_ids: JSON.parse(s.related_action_ids) })),
    occurrences: activeOccurrences(db, id) };
}

/** Which event (source, segment) is already in an ACTIVE physical action? (one event -> at most one active action) */
function activeOwnerOf(db, sourceId, segmentId) {
  const rows = db.prepare(`select o.* from action_occurrences o where o.source_id=? and o.segment_id=?
    and not exists (select 1 from action_occurrence_retirements r where r.occurrence_id=o.id)`).all(sourceId, segmentId);
  return rows.find(o => ACTIVE.has(actionState(db, o.physical_action_id))) ?? null;
}

/** Link the exact event (source + segment id) to a physical action; frames come from the latest approved revision if it has the event, else the draft. */
export function linkOccurrence(db, actionId, { source_id, segment_id, occurrence_role = 'uncertain', actor = 'operator' } = {}) {
  const action = getPhysicalAction(db, actionId);
  if (!ACTIVE.has(action.lineage_state)) throw new ApiError('INVALID_INPUT', 'הפעולה אינה פעילה (מוזגה/פוצלה/בוטלה)');
  if (!ROLES.includes(occurrence_role)) throw new ApiError('INVALID_INPUT', 'תפקיד מופע לא תקין');
  const rev = latestRevision(db, source_id);
  const revSeg = rev ? JSON.parse(rev.content).segments.find(s => s.id === segment_id) : null;
  const seg = revSeg ?? getDraft(db, source_id).content.segments.find(s => s.id === segment_id);
  if (!seg) throw new ApiError('NOT_FOUND', 'האירוע לא נמצא במקור');
  const owner = activeOwnerOf(db, source_id, segment_id);
  if (owner) throw new ApiError('INVALID_INPUT', owner.physical_action_id === actionId ? 'האירוע כבר מקושר לפעולה זו' : 'האירוע כבר שייך לפעולה פיזית אחרת — פצל/מזג במקום קישור כפול');
  if (occurrence_role === 'canonical_view' && action.occurrences.some(o => o.occurrence_role === 'canonical_view')) throw new ApiError('INVALID_INPUT', 'כבר קיים מופע קנוני לפעולה זו');
  const id = randomUUID();
  db.prepare('insert into action_occurrences(id,physical_action_id,source_id,segment_id,evidence_revision_id,start_frame,end_frame,occurrence_role,created_at) values(?,?,?,?,?,?,?,?,?)')
    .run(id, actionId, source_id, segment_id, revSeg ? rev.id : null, seg.start_frame, seg.end_frame, occurrence_role, now());
  audit(db, actor, 'action_occurrence_linked', actionId, { occurrence: id, source_id, segment_id, occurrence_role });
  return db.prepare('select * from action_occurrences where id=?').get(id);
}

export function retireOccurrence(db, occurrenceId, { reason, actor = 'operator' } = {}) {
  if (!reason) throw new ApiError('INVALID_INPUT', 'חובה לציין סיבה');
  if (!db.prepare('select 1 from action_occurrences where id=?').get(occurrenceId)) throw new ApiError('NOT_FOUND');
  if (db.prepare('select 1 from action_occurrence_retirements where occurrence_id=?').get(occurrenceId)) throw new ApiError('INVALID_INPUT', 'המופע כבר בוטל');
  db.prepare('insert into action_occurrence_retirements(occurrence_id,reason,actor,at) values(?,?,?,?)').run(occurrenceId, reason, actor, now());
  return { retired: occurrenceId };
}

export function setActionState(db, actionId, lineage_state, { reason = null, actor = 'operator' } = {}) {
  if (!['accepted', 'retired'].includes(lineage_state)) throw new ApiError('INVALID_INPUT', 'merge/split נעשים דרך פעולות ייעודיות');
  const a = getPhysicalAction(db, actionId);
  if (!ACTIVE.has(a.lineage_state)) throw new ApiError('INVALID_INPUT', 'הפעולה אינה פעילה');
  pushState(db, actionId, lineage_state, { reason, actor });
  return getPhysicalAction(db, actionId);
}

/** Merge: a NEW action receives every active occurrence; predecessors become 'merged' (history kept). */
export function mergeActions(db, actionIds, { reason, actor = 'operator' } = {}) {
  const ids = [...new Set(actionIds ?? [])];
  if (ids.length < 2 || !reason) throw new ApiError('INVALID_INPUT', 'מיזוג דורש לפחות שתי פעולות וסיבה');
  return tx(db, () => {
    const acts = ids.map(id => getPhysicalAction(db, id));
    if (acts.some(a => !ACTIVE.has(a.lineage_state))) throw new ApiError('INVALID_INPUT', 'אפשר למזג רק פעולות פעילות');
    if (new Set(acts.map(a => a.action_type)).size > 1) throw new ApiError('INVALID_INPUT', 'אי אפשר למזג פעולות מסוגים שונים');
    const nid = randomUUID();
    db.prepare('insert into physical_actions(id,sport_id,action_type,primary_person_id,created_at) values(?,?,?,?,?)').run(nid, acts[0].sport_id, acts[0].action_type, acts.find(a => a.primary_person_id)?.primary_person_id ?? null, now());
    pushState(db, nid, 'provisional', { related: ids, reason, actor });
    for (const a of acts) {
      for (const o of a.occurrences) {
        db.prepare('insert into action_occurrence_retirements(occurrence_id,reason,actor,at) values(?,?,?,?)').run(o.id, `merged into ${nid}`, actor, now());
        db.prepare('insert into action_occurrences(id,physical_action_id,source_id,segment_id,evidence_revision_id,start_frame,end_frame,occurrence_role,created_at) values(?,?,?,?,?,?,?,?,?)')
          .run(randomUUID(), nid, o.source_id, o.segment_id, o.evidence_revision_id, o.start_frame, o.end_frame, o.occurrence_role === 'canonical_view' && a !== acts[0] ? 'duplicate_view' : o.occurrence_role, now());
      }
      pushState(db, a.id, 'merged', { related: [nid], reason, actor });
    }
    audit(db, actor, 'physical_actions_merged', nid, { from: ids, reason });
    return getPhysicalAction(db, nid);
  });
}

/** Split: each group of occurrence ids becomes a NEW action; the original becomes 'split'. */
export function splitAction(db, actionId, groups, { reason, actor = 'operator' } = {}) {
  if (!Array.isArray(groups) || groups.length < 2 || !reason) throw new ApiError('INVALID_INPUT', 'פיצול דורש לפחות שתי קבוצות וסיבה');
  return tx(db, () => {
    const a = getPhysicalAction(db, actionId);
    if (!ACTIVE.has(a.lineage_state)) throw new ApiError('INVALID_INPUT', 'אפשר לפצל רק פעולה פעילה');
    const all = new Set(a.occurrences.map(o => o.id)), used = new Set();
    for (const g of groups) for (const o of g) { if (!all.has(o) || used.has(o)) throw new ApiError('INVALID_INPUT', 'קבוצות הפיצול חייבות לחלק את המופעים ללא חפיפה'); used.add(o); }
    if (used.size !== all.size) throw new ApiError('INVALID_INPUT', 'כל מופע חייב להשתייך לקבוצה אחת');
    const newIds = [];
    for (const g of groups) {
      const nid = randomUUID(); newIds.push(nid);
      db.prepare('insert into physical_actions(id,sport_id,action_type,primary_person_id,created_at) values(?,?,?,?,?)').run(nid, a.sport_id, a.action_type, a.primary_person_id, now());
      pushState(db, nid, 'provisional', { related: [actionId], reason, actor });
      for (const oid of g) {
        const o = a.occurrences.find(x => x.id === oid);
        db.prepare('insert into action_occurrence_retirements(occurrence_id,reason,actor,at) values(?,?,?,?)').run(o.id, `split into ${nid}`, actor, now());
        db.prepare('insert into action_occurrences(id,physical_action_id,source_id,segment_id,evidence_revision_id,start_frame,end_frame,occurrence_role,created_at) values(?,?,?,?,?,?,?,?,?)')
          .run(randomUUID(), nid, o.source_id, o.segment_id, o.evidence_revision_id, o.start_frame, o.end_frame, o.occurrence_role, now());
      }
    }
    pushState(db, actionId, 'split', { related: newIds, reason, actor });
    audit(db, actor, 'physical_action_split', actionId, { into: newIds, reason });
    return newIds.map(id => getPhysicalAction(db, id));
  });
}

export function listPhysicalActions(db, { source_id = null, include_inactive = false } = {}) {
  const ids = source_id
    ? db.prepare('select distinct physical_action_id id from action_occurrences where source_id=?').all(source_id).map(r => r.id)
    : db.prepare('select id from physical_actions order by created_at').all().map(r => r.id);
  return ids.map(id => getPhysicalAction(db, id)).filter(a => include_inactive || ACTIVE.has(a.lineage_state));
}

/** Exactly-once coverage on PhysicalActionEntity (§4): actions vs. event occurrences, duplicates explicit. */
export function actionCoverage(db, sourceIds = null) {
  const acts = listPhysicalActions(db).map(a => ({ ...a, occurrences: a.occurrences.filter(o => !sourceIds || sourceIds.includes(o.source_id)) })).filter(a => a.occurrences.length);
  return { physical_actions: acts.length, occurrences: acts.reduce((n, a) => n + a.occurrences.length, 0),
    multi_view_actions: acts.filter(a => a.occurrences.length > 1).length,
    duplicate_views: acts.reduce((n, a) => n + a.occurrences.filter(o => o.occurrence_role === 'duplicate_view').length, 0),
    accepted: acts.filter(a => a.lineage_state === 'accepted').length, provisional: acts.filter(a => a.lineage_state === 'provisional').length };
}

/** Snapshot pinned into a frozen dataset manifest (§4, §6, §11). */
export function lineageSnapshot(db, sourceIds) {
  const acts = listPhysicalActions(db).map(a => ({ id: a.id, action_type: a.action_type, lineage_state: a.lineage_state, primary_person_id: a.primary_person_id,
    occurrences: a.occurrences.filter(o => sourceIds.includes(o.source_id)).map(o => ({ id: o.id, source_id: o.source_id, segment_id: o.segment_id, role: o.occurrence_role, evidence_revision_id: o.evidence_revision_id })) }))
    .filter(a => a.occurrences.length);
  return { person_lineage_relation_ids: db.prepare("select id from person_lineage_relations where set_id='primary' order by created_at, id").all().map(r => r.id), physical_actions: acts };
}
