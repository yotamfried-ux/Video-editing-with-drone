// Annotation drafts (mutable, optimistic concurrency) and approved revisions (immutable).
import { createHash, randomUUID } from 'node:crypto';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { validateSegmentTaxonomy, stampResolved, taxonomyVersionsFor } from './sports.mjs';
import { validateBoxEvidence, upgradeLegacyBoxQA, trackQaSummary, latestByFrame } from './trackqa.mjs';

export const SCHEMA = 1;
export const DECISIONS = ['include', 'exclude', 'uncertain'];
export const USABILITY = ['usable', 'partially_usable', 'unusable', 'uncertain'];
export const REASON_CODES = [
  'missing_takeoff',
  'missing_landing',
  'occlusion',
  'unclear_identity',
  'capture_issues',
  'no_meaningful_action',
  'duplicate_action',
  'other',
];
export const VERIFICATION_STATUSES = [
  'unreviewed',
  'verified_correct',
  'corrected',
  'wrong_performer',
  'occluded',
  'indeterminate',
];
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
export const emptyContent = () => ({ schema: SCHEMA, segments: [], keyframes: [], reviewed_ranges: [], box_verifications: [] });

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
    if (s.usability != null && !USABILITY.includes(s.usability)) throw new ApiError('INVALID_INPUT', 'שימושיות לא תקינה');
    if (s.reason_codes != null) {
      if (!Array.isArray(s.reason_codes) || !s.reason_codes.every(r => typeof r === 'string')) {
        throw new ApiError('INVALID_INPUT', 'קודי סיבה לא תקינים');
      }
    }
    if (s.key_moments != null && typeof s.key_moments === 'object') {
      const { takeoff_frame, peak_frame, landing_frame, inflection_frames } = s.key_moments;
      for (const f of [takeoff_frame, peak_frame, landing_frame].filter(x => x != null)) {
        if (!isInt(f) || f < s.start_frame || f > s.end_frame) throw new ApiError('INVALID_INTERVAL', 'פריים רגע מפתח מחוץ לטווח');
      }
      if (inflection_frames != null && (!Array.isArray(inflection_frames) || !inflection_frames.every(f => isInt(f) && f >= s.start_frame && f <= s.end_frame))) {
        throw new ApiError('INVALID_INTERVAL', 'פריימי שינוי מחוץ לטווח');
      }
    }
    if (s.framing_mode != null && !FRAMING.includes(s.framing_mode)) throw new ApiError('INVALID_INPUT', 'מצב קומפוזיציה לא תקין');
    if (s.target != null && !(s.target.x >= 0 && s.target.x <= 1 && s.target.y >= 0 && s.target.y <= 1)) throw new ApiError('INVALID_INPUT', 'נקודת יעד לא תקינה');
    if (s.athlete_id != null && !db.prepare('select 1 from athletes where id=?').get(s.athlete_id)) throw new ApiError('INVALID_INPUT', 'גולש לא קיים');
    segs.set(s.id, s);
  }
  const kids = new Set();
  const latestLog = latestByFrame(Array.isArray(c.box_verifications) ? c.box_verifications : []);
  for (const k of c.keyframes) {
    if (!k.id || kids.has(k.id)) throw new ApiError('INVALID_INPUT', 'מזהה קיפריים כפול');
    kids.add(k.id);
    const s = segs.get(k.segment_id);
    if (!s) throw new ApiError('INVALID_INPUT', 'קיפריים ללא מקטע');
    if (!isInt(k.frame) || k.frame < s.start_frame || k.frame >= s.end_frame) throw new ApiError('INVALID_INTERVAL');
    if (!VISIBILITY.includes(k.visibility) || !KEY_ORIGINS.includes(k.origin)) throw new ApiError('INVALID_INPUT', 'מאפיין קיפריים לא תקין');
    if (k.verification_status != null && !VERIFICATION_STATUSES.includes(k.verification_status)) throw new ApiError('INVALID_INPUT', 'סטטוס אימות לא תקין');
    // A keyframe flag is only a mirror; it is backed either by its own legacy stamp or by a bound decision in the log
    // (validateBoxEvidence then proves the log entry matches this exact frame, geometry and performer).
    const backed = latestLog.get(`${k.segment_id}:${k.frame}`)?.status === k.verification_status;
    if (k.origin === 'interpolated' && k.verification_status === 'verified_correct' && !k.verified_at && !backed) {
      throw new ApiError('INVALID_INPUT', 'פריים אינטרפולציה לא יכול להיחשב מאומת ללא אימות מפורש');
    }
    if (k.verification_status === 'verified_correct' && !k.verified_at && !backed) {
      throw new ApiError('INVALID_INPUT', 'אימות תיבה מחייב חותמת זמן ומפעיל מאמת');
    }
    if (k.original_bbox != null) validateBbox(k.original_bbox);
    validateBbox(k.bbox);
  }
  for (const r of c.reviewed_ranges) if (!inRange(r.start_frame, r.end_frame)) throw new ApiError('INVALID_INTERVAL');

  validateBoxEvidence(c, segs);
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
  if (d) {
    const up = upgradeLegacyBoxQA(JSON.parse(d.content));
    return { version: d.version, content: up.content, base_revision_id: d.base_revision_id, updated_at: d.updated_at, legacy_box_qa_upgraded: up.changed };
  }
  const rev = latestRevision(db, sourceId);
  const content = rev ? upgradeLegacyBoxQA(JSON.parse(rev.content)).content : emptyContent();
  return { version: 0, content, base_revision_id: rev?.id ?? null, updated_at: null };
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

const fpsOfSource = src => (src?.fps_num && src?.fps_den ? src.fps_num / src.fps_den : 30);

/**
 * Approval gates (spec §22.2 P0-3). `blocking` items can never be acknowledged away; `acknowledgeable` items require an
 * explicit, audited acknowledgement and are recorded as caveats on the immutable revision. Nothing here ever turns an
 * unchecked frame, an unknown identity or an uncertain usability into a verified/positive label.
 */
export function unresolved(content, source = null) {
  const segs = content.segments || [];
  const qa = trackQaSummary(content, fpsOfSource(source));
  const qaById = new Map(qa.map(q => [q.segment_id, q]));
  const inc = segs.filter(s => s.decision === 'include');
  const needsReason = s => (s.usability === 'partially_usable' || s.usability === 'unusable') && !(Array.isArray(s.reason_codes) && s.reason_codes.length);
  const out = {
    uncertain_segments: segs.filter(s => s.decision === 'uncertain').length,
    unknown_athlete_included: inc.filter(s => !s.athlete_id).length,
    usability_undecided: segs.filter(s => s.usability == null || s.usability === 'uncertain').length,
    included_not_usable: inc.filter(s => s.usability === 'unusable').length,
    missing_reason_codes: segs.filter(needsReason).length,
    needs_review_flags: segs.filter(s => s.needs_review).length,
    boxes_needing_correction: segs.filter(s => qaById.get(s.id)?.status === 'needs_correction').length,
    included_boxes_unverified: inc.filter(s => { const q = qaById.get(s.id); return q?.has_boxes && q.status !== 'verified_in_checked_range'; }).length,
  };
  out.blocking = {
    boxes_needing_correction: out.boxes_needing_correction,
  };
  out.acknowledgeable = {
    uncertain_segments: out.uncertain_segments,
    unknown_athlete_included: out.unknown_athlete_included,
    usability_undecided: out.usability_undecided,
    included_not_usable: out.included_not_usable,
    missing_reason_codes: out.missing_reason_codes,
    needs_review_flags: out.needs_review_flags,
  };
  // Informational caveat recorded on the revision; never blocks, never reported as verified.
  out.caveats = { included_boxes_unverified: out.included_boxes_unverified };
  out.has_blocking = Object.values(out.blocking).some(Boolean);
  out.has_acknowledgeable = Object.values(out.acknowledgeable).some(Boolean);
  out.track_qa = qa.map(q => ({ segment_id: q.segment_id, status: q.status, checked_frames: q.checked_frames, verified_frames: q.verified_frames, box_frames: q.box_frames, checked_range: q.checked_range, event_span_checked_ratio: q.event_span_checked_ratio, missing_checkpoints: q.missing_checkpoints }));
  return out;
}

export function approve(db, sourceId, { expectedVersion, scope = 'source', reason = '', acknowledgeUnresolved = false, author = 'operator' }) {
  const source = getSource(db, sourceId);
  if (source.ingest_state !== 'ready') throw new ApiError('ARCHIVE_UNVERIFIED');
  // Ground Truth on a cloud source is only approved once its identity was re-verified from the bucket's bytes.
  if (source.provider === 'cloud-r2' && source.verify_state !== 'verified') throw new ApiError('SOURCE_UNVERIFIED');
  if (!['source', 'interval', 'segment'].includes(scope)) throw new ApiError('INVALID_INPUT');
  return tx(db, () => {
    const d = db.prepare('select * from annotation_drafts where source_id=?').get(sourceId);
    if (!d || d.version !== expectedVersion) throw new ApiError('VERSION_CONFLICT');
    const content = upgradeLegacyBoxQA(JSON.parse(d.content)).content;
    validateContent(content, source, db);
    stampResolved(content, source);
    const u = unresolved(content, source);
    if (u.has_blocking) throw Object.assign(new ApiError('BLOCKING_ITEMS'), { unresolved: u });
    if (u.has_acknowledgeable && !acknowledgeUnresolved) {
      throw Object.assign(new ApiError('UNRESOLVED_ITEMS'), { unresolved: u });
    }
    // The approval scope and every acknowledged caveat travel with the immutable revision (in its reason/audit).
    const caveats = { scope, acknowledged: u.has_acknowledgeable ? u.acknowledgeable : {}, caveats: u.caveats, track_qa: u.track_qa };
    const parent = latestRevision(db, sourceId);
    const digest = digestOf(content);
    if (parent && parent.digest === digest) return { revision: parent, unchanged: true };
    const id = randomUUID(), t = now();
    const tax = taxonomyVersionsFor(db, content);
    db.prepare(`insert into annotation_revisions(id,source_id,seq,parent_revision_id,content,digest,author,reason,schema_version,scope,created_at,approved_at,taxonomy_versions)
      values(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, sourceId, (parent?.seq ?? 0) + 1, parent?.id ?? null, JSON.stringify(content), digest, author, reason, SCHEMA, scope, t, t, JSON.stringify(tax));
    // Source sport may have been reclassified since the draft was saved: keep the stored draft identical to what was approved.
    db.prepare('update annotation_drafts set content=?, base_revision_id=? where source_id=?').run(JSON.stringify(content), id, sourceId);
    audit(db, author, 'approve_revision', sourceId, { revision: id, digest, unresolved: u, approval_caveats: caveats });
    return { revision: db.prepare('select * from annotation_revisions where id=?').get(id), unchanged: false, unresolved: u, approval_caveats: caveats };
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
  if (content.review_request?.requested || content.segments.some(s => s.decision === 'uncertain' || s.needs_review)) return 'needs_review';
  return 'in_progress';
}

/**
 * Independent operator-facing state axes (spec §21.3). Each axis answers one question and none implies another:
 * saved != owner assigned != frame verified != reviewed coverage != usable != included != approved != frozen.
 */
export function sourceStates(db, sourceId) {
  const src = getSource(db, sourceId);
  const d = db.prepare('select version, content, updated_at from annotation_drafts where source_id=?').get(sourceId);
  const rev = latestRevision(db, sourceId);
  const content = d ? upgradeLegacyBoxQA(JSON.parse(d.content)).content : rev ? JSON.parse(rev.content) : emptyContent();
  const segs = content.segments || [];
  const count = (k, vals) => Object.fromEntries(vals.map(v => [v, segs.filter(x => (x[k] ?? 'uncertain') === v).length]));
  const qa = trackQaSummary(content, fpsOfSource(src));
  const frozen = db.prepare(`select m.dataset_id, v.name, m.revision_id, m.split from dataset_members m join dataset_versions v on v.id=m.dataset_id where m.source_id=?`).all(sourceId);
  const draftEqualsApproved = !!(rev && d && digestOf(JSON.parse(d.content)) === rev.digest);
  const u = unresolved(content, src);
  const operatorRequestedReview = !!content.review_request?.requested;
  let workflow;
  if (!d && !rev) workflow = operatorRequestedReview ? 'needs_review' : 'not_started';
  else if (rev && (!d || draftEqualsApproved)) workflow = 'approved';
  else if (operatorRequestedReview || u.has_blocking || u.needs_review_flags) workflow = 'needs_review';
  else if (!u.has_acknowledgeable && segs.length) workflow = 'ready_for_approval';
  else workflow = 'in_progress';
  return {
    source_id: sourceId,
    workflow, workflow_computed_reasons: { blocking: u.blocking, open: u.acknowledgeable }, operator_requested_review: operatorRequestedReview,
    draft: d ? { saved: true, version: d.version, updated_at: d.updated_at } : { saved: false, version: 0 },
    catalog_owner: { athlete_id: src.owner_athlete_id ?? null, status: src.owner_status || 'unassigned', version: src.owner_version ?? 0 },
    segments: { total: segs.length, usability: count('usability', USABILITY), decision: count('decision', DECISIONS) },
    box_qa: { frames_verified: qa.reduce((a, q) => a + q.verified_frames, 0), per_segment: qa.map(q => ({ segment_id: q.segment_id, status: q.status, checked_frames: q.checked_frames, verified_frames: q.verified_frames, box_frames: q.box_frames, interpolated_frames: q.interpolated_frames, checked_range: q.checked_range, event_span_checked_ratio: q.event_span_checked_ratio, missing_checkpoints: q.missing_checkpoints, needs_correction_frames: q.needs_correction_frames, crossings: q.crossings.length })) },
    reviewed_coverage: reviewedCoverage(content, src.frame_count || 0),
    ground_truth: rev ? { approved: true, latest_seq: rev.seq, latest_revision_id: rev.id, draft_matches_approved: draftEqualsApproved || !d } : { approved: false },
    datasets: { frozen_in: frozen },
    source_identity: { sha256: src.sha256, ingest_state: src.ingest_state, provider: src.provider ?? 'local', verify_state: src.verify_state ?? (src.ingest_state === 'ready' ? 'verified' : 'unverified') },
  };
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
/** Record that a surfer is VISIBLE in a source (spec §21.1.4) — independent of catalog owner and of any event. */
export function addAppearance(db, athleteId, sourceId, { uncertain = false } = {}) {
  if (!db.prepare('select 1 from athletes where id=?').get(athleteId)) throw new ApiError('NOT_FOUND', 'גולש לא קיים');
  getSource(db, sourceId);
  db.prepare('insert or ignore into athlete_appearances(id,athlete_id,source_id,created_at,uncertain,confirmed) values(?,?,?,?,?,?)')
    .run(randomUUID(), athleteId, sourceId, now(), uncertain ? 1 : 0, uncertain ? 0 : 1);
  audit(db, 'operator', 'appearance_recorded', sourceId, { athlete_id: athleteId, uncertain: !!uncertain });
  return db.prepare('select athlete_id, source_id, uncertain, confirmed from athlete_appearances where athlete_id=? and source_id=?').get(athleteId, sourceId);
}
export function listSourceAppearances(db, sourceId) {
  return db.prepare('select athlete_id, uncertain, confirmed, track_label from athlete_appearances where source_id=? order by created_at').all(sourceId);
}
export function listAthletes(db) {
  return db.prepare('select * from athletes order by created_at').all().map(a => ({
    ...a,
    assigned_sources_count: db.prepare('select count(*) as c from sources where owner_athlete_id=?').get(a.id)?.c ?? 0,
    appearances: db.prepare(`select ap.source_id, ap.uncertain, ap.confirmed, ap.track_label, s.display_name from athlete_appearances ap
      join sources s on s.id=ap.source_id where ap.athlete_id=? order by ap.created_at`).all(a.id),
  }));
}
