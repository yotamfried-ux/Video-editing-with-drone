// Annotation drafts (mutable, optimistic concurrency) and approved revisions (immutable).
import { createHash, randomUUID } from 'node:crypto';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { validateSegmentTaxonomy, stampResolved, taxonomyVersionsFor } from './sports.mjs';

export const SCHEMA = 1;
export const DECISIONS = ['include', 'exclude', 'uncertain'];
export const VISIBILITY = ['visible', 'partial', 'occluded', 'not_visible'];
export const KEY_ORIGINS = ['manual', 'suggested', 'interpolated'];
export const FRAMING = ['contain', 'geometric_center', 'directional_lead_room'];
const EPS = 1e-9;

export function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`;
  return JSON.stringify(v);
}
export const digestOf = v => createHash('sha256').update(canonical(v)).digest('hex');
export const emptyContent = () => ({ schema: SCHEMA, segments: [], keyframes: [], reviewed_ranges: [] });

const isInt = n => Number.isInteger(n);

export function validateBbox(b) {
  if (!b || ![b.x, b.y, b.w, b.h].every(n => typeof n === 'number' && Number.isFinite(n))) throw new ApiError('INVALID_BBOX');
  if (b.w <= 0 || b.h <= 0 || b.x < 0 || b.y < 0 || b.x + b.w > 1 + EPS || b.y + b.h > 1 + EPS) throw new ApiError('INVALID_BBOX');
}

export function validateContent(c, source, db) {
  if (!c || c.schema !== SCHEMA || !Array.isArray(c.segments) || !Array.isArray(c.keyframes) || !Array.isArray(c.reviewed_ranges)) {
    throw new ApiError('INVALID_INPUT', 'מבנה מסמך לא תקין');
  }
  const total = source.frame_count;
  const inRange = (s, e) => isInt(s) && isInt(e) && s >= 0 && e > s && e <= total;
  const ids = new Set(), segs = new Map(), taxCache = new Map();
  for (const s of c.segments) {
    if (!s.id || ids.has(s.id)) throw new ApiError('INVALID_INPUT', 'מזהה מקטע כפול');
    ids.add(s.id);
    if (!inRange(s.start_frame, s.end_frame)) throw new ApiError('INVALID_INTERVAL');
    if (!DECISIONS.includes(s.decision)) throw new ApiError('INVALID_INPUT', 'החלטה לא תקינה');
    if (typeof s.event_type !== 'string' || !s.event_type) throw new ApiError('INVALID_INPUT', 'סוג אירוע לא תקין');
    validateSegmentTaxonomy(db, source, s, taxCache);
    if (s.framing_mode != null && !FRAMING.includes(s.framing_mode)) throw new ApiError('INVALID_INPUT', 'מצב קומפוזיציה לא תקין');
    if (s.target != null && !(s.target.x >= 0 && s.target.x <= 1 && s.target.y >= 0 && s.target.y <= 1)) throw new ApiError('INVALID_INPUT', 'נקודת יעד לא תקינה');
    if (s.athlete_id != null && !db.prepare('select 1 from athletes where id=?').get(s.athlete_id)) throw new ApiError('INVALID_INPUT', 'גולש לא קיים');
    segs.set(s.id, s);
  }
  const kids = new Set();
  for (const k of c.keyframes) {
    if (!k.id || kids.has(k.id)) throw new ApiError('INVALID_INPUT', 'מזהה קיפריים כפול');
    kids.add(k.id);
    const s = segs.get(k.segment_id);
    if (!s) throw new ApiError('INVALID_INPUT', 'קיפריים ללא מקטע');
    if (!isInt(k.frame) || k.frame < s.start_frame || k.frame >= s.end_frame) throw new ApiError('INVALID_INTERVAL');
    if (!VISIBILITY.includes(k.visibility) || !KEY_ORIGINS.includes(k.origin)) throw new ApiError('INVALID_INPUT', 'מאפיין קיפריים לא תקין');
    validateBbox(k.bbox);
  }
  for (const r of c.reviewed_ranges) if (!inRange(r.start_frame, r.end_frame)) throw new ApiError('INVALID_INTERVAL');
}

function getSource(db, id) {
  const s = db.prepare('select * from sources where id=?').get(id);
  if (!s) throw new ApiError('NOT_FOUND');
  return s;
}
export const latestRevision = (db, sourceId) =>
  db.prepare('select * from annotation_revisions where source_id=? order by seq desc limit 1').get(sourceId);

export function getDraft(db, sourceId) {
  getSource(db, sourceId);
  const d = db.prepare('select * from annotation_drafts where source_id=?').get(sourceId);
  if (d) return { version: d.version, content: JSON.parse(d.content), base_revision_id: d.base_revision_id, updated_at: d.updated_at };
  const rev = latestRevision(db, sourceId);
  return { version: 0, content: rev ? JSON.parse(rev.content) : emptyContent(), base_revision_id: rev?.id ?? null, updated_at: null };
}

export function saveDraft(db, sourceId, expectedVersion, content) {
  const source = getSource(db, sourceId);
  validateContent(content, source, db);
  stampResolved(content, source);
  return tx(db, () => {
    const cur = db.prepare('select version from annotation_drafts where source_id=?').get(sourceId);
    const curV = cur?.version ?? 0;
    if (curV !== expectedVersion) throw new ApiError('VERSION_CONFLICT');
    const rev = latestRevision(db, sourceId);
    db.prepare(`insert into annotation_drafts(source_id,version,content,base_revision_id,updated_at) values(?,?,?,?,?)
      on conflict(source_id) do update set version=excluded.version, content=excluded.content, updated_at=excluded.updated_at`)
      .run(sourceId, curV + 1, JSON.stringify(content), rev?.id ?? null, now());
    syncAppearances(db, sourceId, content);
    return { version: curV + 1 };
  });
}

function syncAppearances(db, sourceId, content) {
  const t = now();
  for (const a of new Set(content.segments.map(s => s.athlete_id).filter(Boolean))) {
    db.prepare('insert or ignore into athlete_appearances(id,athlete_id,source_id,created_at) values(?,?,?,?)').run(randomUUID(), a, sourceId, t);
  }
}

export function unresolved(content) {
  return {
    uncertain_segments: content.segments.filter(s => s.decision === 'uncertain').length,
    unknown_athlete_included: content.segments.filter(s => s.decision === 'include' && !s.athlete_id).length,
  };
}

export function approve(db, sourceId, { expectedVersion, scope = 'source', reason = '', acknowledgeUnresolved = false, author = 'operator' }) {
  const source = getSource(db, sourceId);
  if (source.ingest_state !== 'ready') throw new ApiError('ARCHIVE_UNVERIFIED');
  if (!['source', 'interval', 'segment'].includes(scope)) throw new ApiError('INVALID_INPUT');
  return tx(db, () => {
    const d = db.prepare('select * from annotation_drafts where source_id=?').get(sourceId);
    if (!d || d.version !== expectedVersion) throw new ApiError('VERSION_CONFLICT');
    const content = JSON.parse(d.content);
    validateContent(content, source, db);
    stampResolved(content, source);
    const u = unresolved(content);
    if ((u.uncertain_segments || u.unknown_athlete_included) && !acknowledgeUnresolved) {
      throw Object.assign(new ApiError('UNRESOLVED_ITEMS'), { unresolved: u });
    }
    const parent = latestRevision(db, sourceId);
    const digest = digestOf(content);
    if (parent && parent.digest === digest) return { revision: parent, unchanged: true };
    const id = randomUUID(), t = now();
    const tax = taxonomyVersionsFor(db, content);
    db.prepare(`insert into annotation_revisions(id,source_id,seq,parent_revision_id,content,digest,author,reason,schema_version,scope,created_at,approved_at,taxonomy_versions)
      values(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, sourceId, (parent?.seq ?? 0) + 1, parent?.id ?? null, JSON.stringify(content), digest, author, reason, SCHEMA, scope, t, t, JSON.stringify(tax));
    // Source sport may have been reclassified since the draft was saved: keep the stored draft identical to what was approved.
    db.prepare('update annotation_drafts set content=?, base_revision_id=? where source_id=?').run(JSON.stringify(content), id, sourceId);
    audit(db, author, 'approve_revision', sourceId, { revision: id, digest, unresolved: u });
    return { revision: db.prepare('select * from annotation_revisions where id=?').get(id), unchanged: false, unresolved: u };
  });
}

export function listRevisions(db, sourceId) {
  getSource(db, sourceId);
  return db.prepare('select id,seq,parent_revision_id,digest,author,reason,scope,created_at,approved_at from annotation_revisions where source_id=? order by seq desc').all(sourceId);
}
export function getRevision(db, revisionId) {
  const r = db.prepare('select * from annotation_revisions where id=?').get(revisionId);
  if (!r) throw new ApiError('NOT_FOUND');
  return { ...r, content: JSON.parse(r.content) };
}

/** not_annotated | in_progress | needs_review | approved */
export function annotationStatus(db, sourceId) {
  const d = db.prepare('select content from annotation_drafts where source_id=?').get(sourceId);
  const rev = latestRevision(db, sourceId);
  if (!d && !rev) return 'not_annotated';
  const content = d ? JSON.parse(d.content) : JSON.parse(rev.content);
  if (rev && (!d || digestOf(content) === rev.digest)) return 'approved';
  if (content.segments.some(s => s.decision === 'uncertain')) return 'needs_review';
  return 'in_progress';
}

export function reviewedCoverage(content, frameCount) {
  const mark = new Uint8Array(frameCount);
  for (const r of content.reviewed_ranges) mark.fill(1, r.start_frame, r.end_frame);
  let n = 0; for (const v of mark) n += v;
  return { reviewed_frames: n, total_frames: frameCount, ratio: frameCount ? n / frameCount : 0 };
}

// ---- athletes ----
export function createAthlete(db, label, notes = null) {
  if (!label || !String(label).trim()) throw new ApiError('INVALID_INPUT');
  const id = randomUUID();
  db.prepare('insert into athletes(id,label,notes,created_at) values(?,?,?,?)').run(id, String(label).trim(), notes, now());
  audit(db, 'operator', 'athlete_created', id, { label });
  return { id, label: String(label).trim(), notes };
}
export function renameAthlete(db, id, label, notes) {
  if (!db.prepare('select 1 from athletes where id=?').get(id)) throw new ApiError('NOT_FOUND');
  db.prepare('update athletes set label=?, notes=coalesce(?,notes) where id=?').run(String(label).trim(), notes ?? null, id);
  audit(db, 'operator', 'athlete_renamed', id, { label });
}
export function setAppearanceFlags(db, athleteId, sourceId, { uncertain, confirmed, track_label }) {
  const a = db.prepare('select * from athlete_appearances where athlete_id=? and source_id=?').get(athleteId, sourceId);
  if (!a) throw new ApiError('NOT_FOUND');
  db.prepare('update athlete_appearances set uncertain=?, confirmed=?, track_label=? where id=?')
    .run(uncertain ?? a.uncertain, confirmed ?? a.confirmed, track_label ?? a.track_label, a.id);
  audit(db, 'operator', 'appearance_updated', a.id, { uncertain, confirmed });
}
export function listAthletes(db) {
  return db.prepare('select * from athletes order by created_at').all().map(a => ({
    ...a,
    appearances: db.prepare(`select ap.source_id, ap.uncertain, ap.confirmed, ap.track_label, s.display_name from athlete_appearances ap
      join sources s on s.id=ap.source_id where ap.athlete_id=? order by ap.created_at`).all(a.id),
  }));
}
