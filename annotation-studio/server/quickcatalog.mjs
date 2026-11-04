// Quick catalog (operator request 2026-11-03): one queue that shows, per video and per event, every catalog field the
// operator records and whether it is filled — owner, sport, "are there events", each event's performer / usability /
// decision / reason codes / BOX track check, and whether the whole video was watched. Nothing is a second copy: every
// value is read from, and written through, the same stores the workbench uses (owner via OCC, sport, the draft).
import { ApiError } from './errors.mjs';
import * as A from './annotations.mjs';
import * as Sp from './sports.mjs';

export const TRIAGE = ['no_events', 'unsure'];
const FULL = 0.999;

/** Per-event checklist. `required: false` items are shown but never block completion (BOX is optional per spec). */
export function eventChecklist(seg, qa, requiredAttrs = []) {
  const noPerformerOk = ['no_primary_action', 'uncertain_primary'].includes(seg.primary_status);
  const needsReason = seg.usability === 'partially_usable' || seg.usability === 'unusable' || seg.decision === 'exclude';
  const hasReason = Array.isArray(seg.reason_codes) && seg.reason_codes.length > 0;
  const items = [
    { key: 'event_type', ok: !!seg.event_type, required: true },
    { key: 'performer', ok: !!seg.athlete_id || noPerformerOk, required: true },
    { key: 'usability', ok: !!seg.usability && seg.usability !== 'uncertain', required: true },
    { key: 'decision', ok: !!seg.decision && seg.decision !== 'uncertain', required: true },
  ];
  if (needsReason) items.push({ key: 'reasons', ok: hasReason, required: true });
  for (const a of requiredAttrs) items.push({ key: `attr:${a}`, ok: seg.attrs?.[a] != null && String(seg.attrs[a]).trim() !== '', required: true });
  items.push({ key: 'notes', ok: !!(seg.notes && String(seg.notes).trim()), required: false });
  const km = seg.key_moments || {};
  items.push({ key: 'key_moments', ok: ['takeoff_frame', 'peak_frame', 'landing_frame'].some(k => km[k] != null), required: false });
  // BOX: optional to draw; once drawn, the track must be checked (a drawn box is not a verified box).
  if (!qa || !qa.box_frames) items.push({ key: 'box', ok: false, required: false, state: 'none' });
  else items.push({ key: 'box', ok: qa.status === 'verified_in_checked_range', required: true, state: qa.status,
    checked: qa.checked_frames, box_frames: qa.box_frames, missing_checkpoints: qa.missing_checkpoints?.length ?? 0, needs_correction: qa.needs_correction_frames?.length ?? 0 });
  return items;
}

export function sourceCatalogState(db, src) {
  const draft = A.getDraft(db, src.id);
  const c = draft.content;
  const segs = c.segments || [];
  const states = A.sourceStates(db, src.id);
  const qaBy = new Map(states.box_qa.per_segment.map(q => [q.segment_id, q]));
  const cov = A.reviewedCoverage(c, src.frame_count || 0);
  const triage = segs.length ? 'has_events' : (c.catalog_triage?.result ?? 'not_started');
  const owner = src.owner_athlete_id ? db.prepare('select id, label from athletes where id=?').get(src.owner_athlete_id) : null;
  const athletes = new Map(db.prepare('select id, label from athletes').all().map(a => [a.id, a.label]));
  const sports = Sp.listSports(db);
  const reqAttrs = (sportId, key) => sports.find(x => x.id === sportId)?.event_types.find(t => t.key === key)?.required_attrs ?? [];
  const occ = db.prepare('select segment_id, physical_action_id, occurrence_role from action_occurrences where source_id=?').all(src.id);
  const events = [...segs].sort((a, b) => a.start_frame - b.start_frame).map(s => {
    const sport = s.sport_id ?? src.primary_sport_id ?? null;
    const required = reqAttrs(sport, s.event_type);
    const checklist = eventChecklist(s, qaBy.get(s.id), required);
    const km = s.key_moments || {};
    // Every value the operator records for an event, so the catalog shows the data itself, not only whether it exists.
    return { id: s.id, start_frame: s.start_frame, end_frame: s.end_frame, event_type: s.event_type, sport_id: s.sport_id ?? null, effective_sport_id: sport,
      athlete_id: s.athlete_id ?? null, athlete_label: s.athlete_id ? athletes.get(s.athlete_id) ?? null : null, primary_status: s.primary_status ?? null,
      usability: s.usability ?? 'uncertain', decision: s.decision, reason_codes: Array.isArray(s.reason_codes) ? s.reason_codes : [],
      key_moments: { takeoff_frame: km.takeoff_frame ?? null, peak_frame: km.peak_frame ?? null, landing_frame: km.landing_frame ?? null },
      notes: s.notes ?? '', attrs: s.attrs ?? {}, required_attrs: required, needs_review: !!s.needs_review,
      boxes: (c.keyframes || []).filter(k => k.segment_id === s.id).length,
      physical_actions: occ.filter(o => o.segment_id === s.id).map(o => ({ id: o.physical_action_id, role: o.occurrence_role })),
      checklist, complete: checklist.every(i => i.ok || !i.required) };
  });
  const appearances = A.listSourceAppearances(db, src.id).map(a => ({ athlete_id: a.athlete_id, label: athletes.get(a.athlete_id) ?? null, uncertain: !!a.uncertain, confirmed: !!a.confirmed }));
  const extraSports = Sp.listSourceSports(db, src.id).all.filter(x => x !== src.primary_sport_id);   // explicit + per-event sports
  const video = [
    { key: 'owner', ok: !!owner && src.owner_status !== 'needs_review', required: true },
    { key: 'sport', ok: !!src.primary_sport_id && src.primary_sport_id !== 'unknown', required: true },
    { key: 'triage', ok: triage === 'has_events' || triage === 'no_events', required: true, state: triage },
  ];
  if (triage === 'has_events') video.push({ key: 'watched', ok: cov.ratio >= FULL, required: true, ratio: cov.ratio });
  const missing = video.filter(i => i.required && !i.ok).length + events.filter(e => !e.complete).length;
  return {
    kind: 'source', source_id: src.id, name: src.display_name, provider: src.provider ?? 'local', frame_count: src.frame_count,
    owner: { athlete_id: owner?.id ?? null, label: owner?.label ?? null, status: src.owner_status ?? 'unassigned', version: src.owner_version ?? 0 },
    sport_id: src.primary_sport_id ?? null, suggested_sport_id: src.suggested_sport_id ?? null, extra_sports: extraSports,
    appearances, coverage: cov.ratio, review_requested: !!c.review_request?.requested,
    identity: { provider: src.provider ?? 'local', verify_state: src.verify_state ?? (src.ingest_state === 'ready' ? 'verified' : 'unverified') },
    draft_version: draft.version, triage, video, events, missing, complete: missing === 0,
    approved: !!states.ground_truth.approved, workflow: states.workflow,
  };
}

export function catalogQueue(db, { include = '', likeContains } = {}) {
  const items = db.prepare('select * from sources order by created_at, id').all().map(s => sourceCatalogState(db, s));
  // Cloud videos not opened yet: shown so the queue covers the whole bucket; opening is read-only on R2.
  let cloud = [];
  try {
    const like = likeContains(include);
    cloud = db.prepare(`select id, key, display_name, available, owner_athlete_id, owner_status, owner_version from cloud_objects
      where source_id is null and available=1 and (? = '' or key like ? escape '\\' or display_name like ? escape '\\') order by uploaded_at desc, key`).all(include, like, like);
  } catch { /* cloud catalog table absent / cloud not configured */ }
  const labels = new Map(db.prepare('select id, label from athletes').all().map(a => [a.id, a.label]));
  for (const o of cloud) {
    items.push({ kind: 'cloud', cloud_object_id: o.id, source_id: null, name: o.display_name ?? o.key, key: o.key,
      owner: { athlete_id: o.owner_athlete_id ?? null, label: o.owner_athlete_id ? labels.get(o.owner_athlete_id) ?? null : null, status: o.owner_status ?? 'unassigned', version: o.owner_version ?? 0 },
      triage: 'not_started', video: [{ key: 'opened', ok: false, required: true }], events: [], missing: 1, complete: false });
  }
  const done = items.filter(i => i.complete).length;
  return { items, totals: { all: items.length, complete: done, remaining: items.length - done } };
}

/**
 * Records the video-level answer to "are there events in this video?". `no_events` is an explicit statement that the
 * operator watched the whole video: it marks the full video as reviewed (coverage) and is refused while events exist.
 * `unsure` raises the existing review request so the video is not counted as catalogued.
 */
export function setTriage(db, sourceId, { result, expected_version, watched_all = false }) {
  if (!TRIAGE.includes(result)) throw new ApiError('INVALID_INPUT', 'תשובה לא תקינה');
  const src = A.getSource(db, sourceId);
  const d = A.getDraft(db, sourceId);
  if (expected_version !== d.version) throw new ApiError('VERSION_CONFLICT');
  const c = structuredClone(d.content);
  const at = new Date().toISOString();
  if (result === 'no_events') {
    if (c.segments.length) throw new ApiError('CATALOG_HAS_EVENTS');
    if (watched_all !== true) throw new ApiError('INVALID_INPUT', 'סימון "אין אירועים" מחייב אישור שצפית בכל הסרטון');
    c.reviewed_ranges = [{ start_frame: 0, end_frame: src.frame_count }];
    c.catalog_triage = { result, at };
    if (c.review_request?.reason === 'catalog_unsure') c.review_request = { requested: false };
  } else {
    c.catalog_triage = { result, at };
    c.review_request = { requested: true, reason: 'catalog_unsure', at };
  }
  return A.saveDraft(db, sourceId, d.version, c);
}
