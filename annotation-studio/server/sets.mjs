// Independent annotation streams (normative addendum v1 §2) and agreement (§8 matching, §9 Jaccard).
//
// * The existing source-keyed drafts/revisions are the 'primary' set; nothing is copied or rewritten.
// * Every other set (delayed blind re-annotation, independent QA, adjudication) keeps assignment-scoped state:
//   its own draft, OCC version, queue status, revision head and resume position per (set, source).
// * A new assignment ALWAYS starts empty — it never sees another set's work.
// * A set's revisions/agreement may be read from another set only after the reading set is submitted
//   (an adjudication set may read its contributing sets once those are submitted).
// * Submitted primary/re-annotation/QA sets are immutable; adjudication never overwrites contributing sets.
import { randomUUID } from 'node:crypto';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { validateContent, emptyContent, digestOf, latestRevision, REASON_CODES, DECISIONS, USABILITY } from './annotations.mjs';
import { stampResolved } from './sports.mjs';

export const PURPOSES = ['delayed_blind_reannotation', 'independent_qa', 'adjudication'];
export const AGREEMENT_MATCHING_VERSION = 'agreement-match-1';      // addendum §8 ranking; changes => new version id
export const AGREEMENT_CONFIG = Object.freeze({ min_temporal_iou: 0.3, version: AGREEMENT_MATCHING_VERSION });

const getSet = (db, id) => { const s = db.prepare('select * from annotation_sets where id=?').get(id); if (!s) throw new ApiError('NOT_FOUND', 'סט תיוג לא נמצא'); return s; };
export function setStatus(db, id) {
  if (id === 'primary') return 'active';
  return db.prepare('select status from annotation_set_status where set_id=? order by id desc limit 1').get(id)?.status ?? 'draft';
}
function pushStatus(db, id, status, actor = 'operator') {
  db.prepare('insert into annotation_set_status(set_id,status,actor,at) values(?,?,?,?)').run(id, status, actor, now());
}

export function createSet(db, { purpose, annotator_id, contributing_set_ids = [], instruction_version = 'guidelines-v1', taxonomy_version = null } = {}) {
  if (!PURPOSES.includes(purpose)) throw new ApiError('INVALID_INPUT', 'מטרת סט לא תקינה');
  if (!annotator_id || !String(annotator_id).trim()) throw new ApiError('INVALID_INPUT', 'חובה לציין מזהה מתייג (פסאודונימי)');
  const contrib = [...new Set(contributing_set_ids)];
  if (purpose === 'adjudication') {
    if (contrib.length < 2) throw new ApiError('INVALID_INPUT', 'סט הכרעה דורש לפחות שני סטים תורמים');
    for (const c of contrib) { getSet(db, c); if (!isClosedForComparison(db, c)) throw new ApiError('SET_NOT_SUBMITTED', `הסט ${c} טרם הוגש — אי אפשר להכריע לפני הגשה`); }
  } else if (contrib.length) throw new ApiError('INVALID_INPUT', 'רק סט הכרעה מפנה לסטים תורמים');
  const id = randomUUID();
  return tx(db, () => {
    db.prepare('insert into annotation_sets(id,purpose,taxonomy_version,instruction_version,annotator_id,contributing_set_ids,created_at) values(?,?,?,?,?,?,?)')
      .run(id, purpose, taxonomy_version, instruction_version, String(annotator_id).trim(), JSON.stringify(contrib), now());
    pushStatus(db, id, purpose === 'adjudication' ? 'adjudicating' : 'active');
    audit(db, 'operator', 'annotation_set_created', id, { purpose, contributing_set_ids: contrib });
    return { ...getSet(db, id), status: setStatus(db, id) };
  });
}

export function listSets(db) {
  return db.prepare('select * from annotation_sets order by created_at').all().map(s => ({
    ...s, contributing_set_ids: JSON.parse(s.contributing_set_ids), status: setStatus(db, s.id),
    assignments: s.id === 'primary' ? null : db.prepare('select queue_status, count(*) n from set_assignments where set_id=? group by queue_status').all(s.id),
  }));
}

const writable = (db, setId) => {
  if (setId === 'primary') throw new ApiError('INVALID_INPUT', 'הסט הראשי נערך דרך מסך הסימון הרגיל');
  const st = setStatus(db, setId);
  if (!['active', 'adjudicating'].includes(st)) throw new ApiError('SET_IMMUTABLE', 'הסט הוגש/ננעל ואינו ניתן לשינוי');
};

export function addAssignments(db, setId, sourceIds) {
  getSet(db, setId); writable(db, setId);
  if (!Array.isArray(sourceIds) || !sourceIds.length) throw new ApiError('INVALID_INPUT');
  return tx(db, () => {
    let added = 0;
    for (const sid of sourceIds) {
      if (!db.prepare('select 1 from sources where id=?').get(sid)) throw new ApiError('NOT_FOUND', `מקור לא נמצא: ${sid}`);
      const r = db.prepare('insert or ignore into set_assignments(id,set_id,source_id,updated_at) values(?,?,?,?)').run(randomUUID(), setId, sid, now());
      added += r.changes;
    }
    audit(db, 'operator', 'set_assignments_added', setId, { added });
    return { added };
  });
}

function getAssignment(db, setId, sourceId) {
  const a = db.prepare('select * from set_assignments where set_id=? and source_id=?').get(setId, sourceId);
  if (!a) throw new ApiError('NOT_FOUND', 'המקור אינו משויך לסט זה');
  return a;
}

/** The set's OWN working state for a source. Never falls back to another set's content. */
export function getSetDraft(db, setId, sourceId) {
  getSet(db, setId);
  const a = getAssignment(db, setId, sourceId);
  return { set_id: setId, source_id: sourceId, version: a.draft_version, queue_status: a.queue_status, playback_position_ms: a.playback_position_ms,
    current_revision_id: a.current_revision_id, content: a.draft_content ? JSON.parse(a.draft_content) : emptyContent() };
}

export function saveSetDraft(db, setId, sourceId, { expected_version, content, playback_position_ms } = {}) {
  getSet(db, setId); writable(db, setId);
  const src = db.prepare('select * from sources where id=?').get(sourceId);
  if (!src) throw new ApiError('NOT_FOUND');
  if (!Number.isInteger(expected_version)) throw new ApiError('INVALID_INPUT', 'expected_version חובה');
  validateContent(content, src, db);
  stampResolved(content, src);
  return tx(db, () => {
    const a = getAssignment(db, setId, sourceId);
    if (a.queue_status === 'completed') throw new ApiError('SET_IMMUTABLE', 'המקור הוגש בסט זה');
    if (a.draft_version !== expected_version) throw new ApiError('VERSION_CONFLICT');
    const t = now();
    const u = db.prepare(`update set_assignments set draft_version=?, draft_content=?, queue_status=?, playback_position_ms=?, started_at=coalesce(started_at,?), updated_at=?
      where id=? and draft_version=?`).run(a.draft_version + 1, JSON.stringify(content), a.queue_status === 'unlabeled' ? 'in_progress' : a.queue_status,
      Number.isInteger(playback_position_ms) ? playback_position_ms : a.playback_position_ms, t, t, a.id, a.draft_version);
    if (!u.changes) throw new ApiError('VERSION_CONFLICT');
    return { version: a.draft_version + 1 };
  });
}

export function setQueueStatus(db, setId, sourceId, queue_status) {
  getSet(db, setId); writable(db, setId);
  if (!['in_progress', 'needs_review', 'excluded'].includes(queue_status)) throw new ApiError('INVALID_INPUT');
  const a = getAssignment(db, setId, sourceId);
  if (a.queue_status === 'completed') throw new ApiError('SET_IMMUTABLE');
  db.prepare('update set_assignments set queue_status=?, updated_at=? where id=?').run(queue_status, now(), a.id);
  return { queue_status };
}

/** Completes one assignment: its draft becomes an immutable set revision (the assignment's revision head). */
export function completeAssignment(db, setId, sourceId, { expected_version, author = 'operator' } = {}) {
  getSet(db, setId); writable(db, setId);
  const src = db.prepare('select * from sources where id=?').get(sourceId);
  return tx(db, () => {
    const a = getAssignment(db, setId, sourceId);
    if (a.draft_version !== expected_version) throw new ApiError('VERSION_CONFLICT');
    if (!a.draft_content) throw new ApiError('INVALID_INPUT', 'אין תוכן להגשה');
    const content = JSON.parse(a.draft_content);
    validateContent(content, src, db);
    const seq = (db.prepare('select max(seq) m from set_revisions where set_id=? and source_id=?').get(setId, sourceId)?.m ?? 0) + 1;
    const id = randomUUID(), digest = digestOf(content), t = now();
    db.prepare('insert into set_revisions(id,set_id,source_id,seq,content,digest,author,created_at) values(?,?,?,?,?,?,?,?)').run(id, setId, sourceId, seq, JSON.stringify(content), digest, author, t);
    db.prepare("update set_assignments set queue_status='completed', current_revision_id=?, completed_at=?, updated_at=? where id=?").run(id, t, t, a.id);
    audit(db, author, 'set_assignment_completed', setId, { source_id: sourceId, revision: id, digest });
    return { revision_id: id, digest };
  });
}

/** Submitting a set freezes it. Every assignment must be completed or excluded. */
export function submitSet(db, setId, actor = 'operator') {
  const s = getSet(db, setId); writable(db, setId);
  const open = db.prepare("select count(*) n from set_assignments where set_id=? and queue_status not in ('completed','excluded')").get(setId).n;
  if (open) throw new ApiError('INVALID_INPUT', `${open} מקורות בסט טרם הושלמו או הוחרגו`);
  return tx(db, () => { pushStatus(db, setId, s.purpose === 'adjudication' ? 'accepted' : 'submitted', actor); audit(db, actor, 'annotation_set_submitted', setId, {}); return { status: setStatus(db, setId) }; });
}

const isClosedForComparison = (db, setId) => setId === 'primary' || ['submitted', 'accepted', 'archived'].includes(setStatus(db, setId));

/** Read another set's submitted content for one source, enforcing isolation from the viewer's point of view. */
export function readForComparison(db, setId, sourceId, { viewerSetId } = {}) {
  const target = getSet(db, setId);
  if (viewerSetId && viewerSetId !== setId) {
    const viewer = getSet(db, viewerSetId);
    const viewerMayRead = isClosedForComparison(db, viewerSetId)
      || (viewer.purpose === 'adjudication' && JSON.parse(viewer.contributing_set_ids).includes(setId));
    if (!viewerMayRead) throw new ApiError('SET_ISOLATION', 'אין לצפות בעבודה של סט אחר לפני הגשת הסט שלך');
  }
  if (!isClosedForComparison(db, setId)) throw new ApiError('SET_NOT_SUBMITTED', 'הסט טרם הוגש');
  if (target.id === 'primary') {
    const rev = latestRevision(db, sourceId);
    return rev ? { revision_id: rev.id, content: JSON.parse(rev.content) } : null;
  }
  const rev = db.prepare('select * from set_revisions where set_id=? and source_id=? order by seq desc limit 1').get(setId, sourceId);
  return rev ? { revision_id: rev.id, content: JSON.parse(rev.content) } : null;
}

// ---------------- agreement (§8 deterministic matching + §9 Jaccard) ----------------
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const iou = (a, b) => { const i = Math.max(0, Math.min(a.end_frame, b.end_frame) - Math.max(a.start_frame, b.start_frame)); const u = Math.max(a.end_frame, b.end_frame) - Math.min(a.start_frame, b.start_frame); return u > 0 ? i / u : 0; };
const sportOf = s => s.sport_id ?? s.resolved_sport_id ?? null;

/** Jaccard over deduplicated exact codes. Both empty => 1, exactly one empty => 0; unknown codes => invalid (null). */
export function jaccard(a = [], b = [], known = REASON_CODES) {
  const A = new Set(a), B = new Set(b);
  if ([...A, ...B].some(x => !known.includes(x))) return { value: null, invalid: true };
  if (!A.size && !B.size) return { value: 1 };
  if (!A.size || !B.size) return { value: 0 };
  let inter = 0; for (const x of A) if (B.has(x)) inter++;
  return { value: inter / (A.size + B.size - inter) };
}

/** One-to-one deterministic event matching (addendum §8): compatible type + sport, IoU >= threshold,
 *  rank by IoU desc, then combined |Δstart|+|Δend| asc, then truth id, then prediction id; greedy. */
export function matchEvents(A, B, { min_temporal_iou } = AGREEMENT_CONFIG) {
  if (!(typeof min_temporal_iou === 'number' && min_temporal_iou > 0 && min_temporal_iou <= 1)) return { inconclusive: true, reason: 'invalid_matching_config' };
  const pairs = [];
  for (const a of A) for (const b of B) {
    if (a.event_type !== b.event_type || sportOf(a) !== sportOf(b)) continue;
    const v = iou(a, b); if (v < min_temporal_iou) continue;
    pairs.push({ a, b, iou: v, err: Math.abs(a.start_frame - b.start_frame) + Math.abs(a.end_frame - b.end_frame) });
  }
  pairs.sort((x, y) => y.iou - x.iou || x.err - y.err || cmp(x.a.id, y.a.id) || cmp(x.b.id, y.b.id));
  const ua = new Set(), ub = new Set(), matched = [];
  for (const p of pairs) if (!ua.has(p.a.id) && !ub.has(p.b.id)) { ua.add(p.a.id); ub.add(p.b.id); matched.push(p); }
  return { matched, only_a: A.filter(x => !ua.has(x.id)), only_b: B.filter(x => !ub.has(x.id)) };
}

const usableClass = u => (u === 'usable' || u === 'partially_usable' ? 'usable' : u === 'unusable' ? 'unusable' : 'uncertain');

export function compareContents(ca, cb, config = AGREEMENT_CONFIG) {
  const m = matchEvents(ca.segments, cb.segments, config);
  if (m.inconclusive) return { status: 'inconclusive', reason: m.reason };
  const pairs = m.matched.map(p => {
    const j = jaccard(p.a.reason_codes ?? [], p.b.reason_codes ?? []);
    return { a: p.a.id, b: p.b.id, iou: p.iou, boundary_error: p.err,
      decision_equal: p.a.decision === p.b.decision, usability_equal: p.a.usability === p.b.usability,
      usability_class_equal: usableClass(p.a.usability) === usableClass(p.b.usability),
      reason_jaccard: j.value, reason_invalid: !!j.invalid,
      reason_exact: !j.invalid && JSON.stringify([...new Set(p.a.reason_codes ?? [])].sort()) === JSON.stringify([...new Set(p.b.reason_codes ?? [])].sort()),
      aAth: p.a.athlete_id ?? null, bAth: p.b.athlete_id ?? null };
  });
  // Identity: set-scoped namespaces => compare PARTITIONS (same-person / different-person pairs), never raw codes.
  let idPairs = 0, idAgree = 0, idSkipped = 0;
  for (let i = 0; i < pairs.length; i++) for (let k = i + 1; k < pairs.length; k++) {
    const p = pairs[i], q = pairs[k];
    if (!p.aAth || !q.aAth || !p.bAth || !q.bAth) { idSkipped++; continue; }
    idPairs++; if ((p.aAth === q.aAth) === (p.bAth === q.bAth)) idAgree++;
  }
  const blocking = [];
  for (const x of m.only_a) if (x.decision === 'include') blocking.push({ type: 'unmatched_included', side: 'a', segment_id: x.id });
  for (const x of m.only_b) if (x.decision === 'include') blocking.push({ type: 'unmatched_included', side: 'b', segment_id: x.id });
  for (const p of pairs) {
    if (!p.decision_equal && [p.a, p.b].length) blocking.push({ type: 'decision_disagreement', a: p.a, b: p.b });
    if (!p.usability_class_equal) blocking.push({ type: 'usability_disagreement', a: p.a, b: p.b });
    if (p.reason_invalid) blocking.push({ type: 'reason_codes_invalid', a: p.a, b: p.b });
  }
  if (idPairs > idAgree) blocking.push({ type: 'identity_partition_disagreement', disagreeing_pairs: idPairs - idAgree });
  const js = pairs.map(p => p.reason_jaccard).filter(v => v != null);
  const perLabel = {};
  for (const p of m.matched) for (const code of new Set([...(p.a.reason_codes ?? []), ...(p.b.reason_codes ?? [])])) {
    const L = perLabel[code] ??= { both: 0, only_a: 0, only_b: 0 };
    const inA = (p.a.reason_codes ?? []).includes(code), inB = (p.b.reason_codes ?? []).includes(code);
    if (inA && inB) L.both++; else if (inA) L.only_a++; else L.only_b++;
  }
  return {
    status: 'complete', matching_version: config.version, min_temporal_iou: config.min_temporal_iou,
    events_a: ca.segments.length, events_b: cb.segments.length, matched: pairs.length, only_a: m.only_a.map(x => x.id), only_b: m.only_b.map(x => x.id),
    decision_agreement: pairs.length ? pairs.filter(p => p.decision_equal).length / pairs.length : null,
    usability_agreement: pairs.length ? pairs.filter(p => p.usability_equal).length / pairs.length : null,
    reason_jaccard_mean: js.length ? js.reduce((s, v) => s + v, 0) / js.length : null,
    reason_exact_set_agreement: pairs.length ? pairs.filter(p => p.reason_exact).length / pairs.length : null,
    reason_per_label: perLabel,
    identity_pair_agreement: idPairs ? idAgree / idPairs : null, identity_pairs: idPairs, identity_pairs_skipped: idSkipped,
    pairs: pairs.map(({ aAth, bAth, ...p }) => p), blocking_disagreements: blocking,
  };
}

/** Agreement report between two closed sets over their common sources. Never readable before both are submitted. */
export function agreementReport(db, setA, setB, { viewerSetId, config = AGREEMENT_CONFIG } = {}) {
  if (setA === setB) throw new ApiError('INVALID_INPUT');
  getSet(db, setA); getSet(db, setB);
  if (!isClosedForComparison(db, setA) || !isClosedForComparison(db, setB)) throw new ApiError('SET_NOT_SUBMITTED', 'השוואה אפשרית רק אחרי הגשת שני הסטים');
  const srcOf = id => (id === 'primary'
    ? db.prepare('select distinct source_id from annotation_revisions').all()
    : db.prepare("select source_id from set_assignments where set_id=? and queue_status='completed'").all(id)).map(r => r.source_id);
  const common = srcOf(setA).filter(s => srcOf(setB).includes(s)).sort();
  const per = common.map(sid => {
    const ra = readForComparison(db, setA, sid, { viewerSetId }), rb = readForComparison(db, setB, sid, { viewerSetId });
    return { source_id: sid, revision_a: ra.revision_id, revision_b: rb.revision_id, ...compareContents(ra.content, rb.content, config) };
  });
  const report = { set_a: setA, set_b: setB, matching_version: config.version, sources: per.length,
    blocking_total: per.reduce((n, p) => n + (p.blocking_disagreements?.length ?? 0), 0), per_source: per };
  return { ...report, digest: digestOf(report) };
}

/** Sources whose independent comparison with the primary set has blocking disagreements not covered by an accepted adjudication. */
export function unadjudicatedDisagreements(db, sourceIds) {
  const independents = db.prepare("select id from annotation_sets where purpose in ('delayed_blind_reannotation','independent_qa')").all().map(r => r.id).filter(id => isClosedForComparison(db, id));
  const accepted = db.prepare("select id, contributing_set_ids from annotation_sets where purpose='adjudication'").all().filter(s => setStatus(db, s.id) === 'accepted');
  const out = [];
  for (const sid of sourceIds) for (const setId of independents) {
    const rb = db.prepare("select content from set_revisions where set_id=? and source_id=? order by seq desc limit 1").get(setId, sid);
    const ra = latestRevision(db, sid);
    if (!rb || !ra) continue;
    const r = compareContents(JSON.parse(ra.content), JSON.parse(rb.content));
    if (!r.blocking_disagreements?.length) continue;
    const covered = accepted.some(a => JSON.parse(a.contributing_set_ids).includes(setId) && db.prepare('select 1 from set_revisions where set_id=? and source_id=?').get(a.id, sid));
    if (!covered) out.push({ source_id: sid, set_id: setId, blocking: r.blocking_disagreements.length });
  }
  return out;
}
export { DECISIONS, USABILITY };
