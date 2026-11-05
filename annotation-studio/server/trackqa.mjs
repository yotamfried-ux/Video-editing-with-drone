// BOX truthfulness (spec §21.2, §22.2 P0-1) and per-segment track QA (§21.3).
//
// Model
// -----
// * A keyframe is a *candidate* box at one exact source frame of one segment (normalized to the ORIGINAL source frame,
//   never to the proxy). Its origin (manual / interpolated / suggested) says how the geometry was produced, never
//   whether a human checked it.
// * `box_verifications` is an append-only per-frame history of human decisions. For each (segment, frame) only the
//   LATEST entry is in force; earlier entries are kept as review evidence (who checked what, and what was corrected).
// * A positive decision (`verified_correct` / `corrected`) is bound to the exact geometry and performer it attests:
//   it carries a `bbox` snapshot and `athlete_id`, and is only accepted when, at save time, an actual keyframe exists at
//   that exact frame with that same geometry, the segment's performer is that same athlete, and the box is visible.
//   Editing the box or changing the performer therefore requires an explicit new entry (re-check or invalidation);
//   documents carrying a stale positive decision are rejected, so a direct API call cannot manufacture a verification.
// * Track QA is derived, never stored as a claim: a single checked frame never verifies a track, and no span is called
//   verified unless every required checkpoint (start / middle / end / risk frames) has a human decision.
import { ApiError } from './errors.mjs';

export const POSITIVE = new Set(['verified_correct', 'corrected']);
export const DECIDED = new Set(['verified_correct', 'corrected', 'wrong_performer', 'occluded', 'indeterminate']);
export const INVALIDATION_REASONS = ['geometry_changed', 'performer_changed', 'keyframe_removed', 'segment_changed', 'legacy_unbound', 'operator_reset'];
export const TRACK_QA = ['not_checked', 'partially_checked', 'verified_in_checked_range', 'needs_correction', 'cannot_determine'];
const BOX_EPS = 1e-6;
const isInt = n => Number.isInteger(n);
const finite = n => typeof n === 'number' && Number.isFinite(n);

export function boxEq(a, b) {
  return !!a && !!b && ['x', 'y', 'w', 'h'].every(k => finite(a[k]) && finite(b[k]) && Math.abs(a[k] - b[k]) <= BOX_EPS);
}
function validBox(b) {
  return !!b && ['x', 'y', 'w', 'h'].every(k => finite(b[k])) && b.w > 0 && b.h > 0 && b.x >= 0 && b.y >= 0 && b.x + b.w <= 1 + 1e-9 && b.y + b.h <= 1 + 1e-9;
}
const ts = v => (typeof v === 'string' && !Number.isNaN(Date.parse(v)) ? Date.parse(v) : NaN);

/**
 * Latest entry per `${segment_id}:${frame}`. The log is append-only, so ARRAY POSITION decides which decision is in force;
 * client-supplied timestamps never do (a future-dated entry cannot shadow a later wrong-performer flag).
 */
export function latestByFrame(verifications) {
  const m = new Map();
  for (const v of Array.isArray(verifications) ? verifications : []) if (v && typeof v === 'object') m.set(`${v.segment_id}:${v.frame}`, v);
  return m;
}

/**
 * Strict validation of BOX evidence; throws ApiError. `segs` is a Map(segment_id -> segment).
 * Called from validateContent, i.e. on every draft save and approval.
 */
export function validateBoxEvidence(c, segs) {
  const kfAt = new Map();
  for (const k of c.keyframes) kfAt.set(`${k.segment_id}:${k.frame}`, k);
  const vs = c.box_verifications ?? [];
  if (!Array.isArray(vs)) throw new ApiError('INVALID_INPUT', 'מבנה אימותי תיבה לא תקין');
  for (const v of vs) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new ApiError('INVALID_INPUT', 'רשומת אימות תיבה לא תקינה');
    if (ts(v.verified_at) > Date.now() + 5 * 60 * 1000) throw new ApiError('INVALID_INPUT', 'חותמת זמן של החלטת בדיקה אינה יכולה להיות בעתיד');
    const s = segs.get(v?.segment_id);
    if (!s) throw new ApiError('INVALID_INPUT', 'אימות תיבה ללא מקטע');
    if (!isInt(v.frame) || v.frame < s.start_frame || v.frame >= s.end_frame) throw new ApiError('INVALID_INTERVAL', 'אימות תיבה מחוץ לטווח המקטע');
    const status = v.status ?? 'unreviewed';
    if (status !== 'unreviewed' && !DECIDED.has(status)) throw new ApiError('INVALID_INPUT', 'סטטוס אימות לא תקין');
    if (Number.isNaN(ts(v.verified_at)) || typeof v.verified_by !== 'string' || !v.verified_by.trim()) {
      throw new ApiError('INVALID_INPUT', 'כל החלטת בדיקה מחייבת מפעיל מאמת וחותמת זמן תקינה');
    }
    if (status === 'unreviewed' && v.invalidation != null && !INVALIDATION_REASONS.includes(v.invalidation)) {
      throw new ApiError('INVALID_INPUT', 'סיבת ביטול אימות לא תקינה');
    }
    if (v.bbox != null && !validBox(v.bbox)) throw new ApiError('INVALID_BBOX');
    if (v.original_bbox != null && !validBox(v.original_bbox)) throw new ApiError('INVALID_BBOX');
    if (v.corrected_bbox != null && !validBox(v.corrected_bbox)) throw new ApiError('INVALID_BBOX');
    if (POSITIVE.has(status) || status === 'wrong_performer') {
      // Every positive or negative judgement records exactly which geometry was looked at and for whom.
      if (!v.bbox) throw new ApiError('BOX_NOT_AT_FRAME', 'החלטת אימות חייבת לכלול את ה-BOX שנבדק בפריים');
      if (POSITIVE.has(status) && !v.athlete_id) throw new ApiError('BOX_IDENTITY_MISMATCH', 'לא ניתן לאמת BOX ללא גולש מבצע ידוע');
    }
  }
  const latest = latestByFrame(vs);
  for (const [key, v] of latest) {
    const status = v.status ?? 'unreviewed';
    const s = segs.get(v.segment_id);
    const k = kfAt.get(key);
    if (POSITIVE.has(status)) {
      if (!k || !validBox(k.bbox)) throw new ApiError('BOX_NOT_AT_FRAME', `לא קיים BOX בפריים ${v.frame} של המקטע — לא ניתן לאשר`);
      if (!boxEq(k.bbox, v.bbox)) throw new ApiError('STALE_BOX_VERIFICATION', `ה-BOX בפריים ${v.frame} שונה אחרי האימות — נדרשת בדיקה מחדש`);
      if (!s.athlete_id || s.athlete_id !== v.athlete_id) throw new ApiError('BOX_IDENTITY_MISMATCH', `האימות בפריים ${v.frame} אינו תואם לגולש המבצע הנוכחי`);
      if (k.visibility === 'not_visible' || k.visibility === 'occluded') throw new ApiError('INVALID_INPUT', `לא ניתן לאמת BOX על גולש שסומן כמוסתר/לא נראה (פריים ${v.frame})`);
    }
  }
  // Per-keyframe convenience flags may never claim more than the evidence log says.
  for (const k of c.keyframes) {
    if (!POSITIVE.has(k.verification_status)) continue;
    const v = latest.get(`${k.segment_id}:${k.frame}`);
    if (!v || !POSITIVE.has(v.status) || !boxEq(v.bbox, k.bbox)) {
      throw new ApiError('STALE_BOX_VERIFICATION', `קיפריים בפריים ${k.frame} מסומן כמאומת ללא החלטת אימות תקפה`);
    }
  }
}

/**
 * Read-side upgrade of drafts saved before geometry binding existed. Never touches approved revisions.
 * A legacy positive decision is bound only when an exact-frame keyframe and the current performer still support it;
 * otherwise an explicit `legacy_unbound` invalidation is appended (the old entry stays as history). Returns
 * { content, changed }.
 */
export function upgradeLegacyBoxQA(content) {
  if (!content || !Array.isArray(content.keyframes)) return { content, changed: false };
  let changed = false;
  const c = structuredClone(content);
  if (!Array.isArray(c.box_verifications)) { c.box_verifications = []; changed = true; }
  const segs = new Map((c.segments || []).map(s => [s.id, s]));
  const kfAt = new Map(c.keyframes.map(k => [`${k.segment_id}:${k.frame}`, k]));
  for (const v of c.box_verifications) {
    if (!v.verified_by) { v.verified_by = 'operator'; changed = true; }
    if (Number.isNaN(ts(v.verified_at))) { v.verified_at = new Date(0).toISOString(); changed = true; }
    if ((POSITIVE.has(v.status) || v.status === 'wrong_performer') && !v.bbox) {
      const k = kfAt.get(`${v.segment_id}:${v.frame}`);
      if (k && validBox(k.bbox)) { v.bbox = { ...k.bbox }; v.legacy_bound = true; changed = true; }
    }
  }
  const latest = latestByFrame(c.box_verifications);
  const add = [];
  for (const [key, v] of latest) {
    if (!POSITIVE.has(v.status) && v.status !== 'wrong_performer') continue;
    const s = segs.get(v.segment_id), k = kfAt.get(key);
    const ok = v.status === 'wrong_performer' ? !!v.bbox
      : !!(s && k && v.bbox && boxEq(k.bbox, v.bbox) && s.athlete_id && (v.athlete_id ?? s.athlete_id) === s.athlete_id && k.visibility !== 'not_visible' && k.visibility !== 'occluded');
    if (ok && POSITIVE.has(v.status) && !v.athlete_id) { v.athlete_id = s.athlete_id; changed = true; }
    if (!ok) {
      if (!v.bbox) v.bbox = k && validBox(k.bbox) ? { ...k.bbox } : undefined;
      if (!v.bbox) delete v.bbox;
      add.push({ segment_id: v.segment_id, frame: v.frame, status: 'unreviewed', invalidation: 'legacy_unbound',
        verified_by: 'system-upgrade', verified_at: new Date(Math.max(ts(v.verified_at) + 1, Date.now())).toISOString(),
        notes: 'אימות ישן שאינו קשור ל-BOX תקף בפריים — נדרשת בדיקה מחדש' });
    }
  }
  // Legacy entries that remain positive/wrong without a bbox snapshot cannot be valid evidence: neutralize them.
  for (const v of c.box_verifications) {
    if ((POSITIVE.has(v.status) || v.status === 'wrong_performer') && !v.bbox) {
      v.legacy_status = v.status; v.status = 'unreviewed'; v.invalidation = 'legacy_unbound'; changed = true;
    }
  }
  if (add.length) { c.box_verifications.push(...add); changed = true; }
  const latest2 = latestByFrame(c.box_verifications);
  for (const k of c.keyframes) {
    if (!POSITIVE.has(k.verification_status) && k.verification_status !== 'wrong_performer') continue;
    const v = latest2.get(`${k.segment_id}:${k.frame}`);
    const eff = v && (POSITIVE.has(v.status) ? boxEq(v.bbox, k.bbox) : true) ? v.status : 'unreviewed';
    if (k.verification_status !== eff) { k.verification_status = eff; changed = true; }
  }
  return { content: changed ? c : content, changed };
}

// ---------------- derived track QA ----------------
function interpAt(kfs, f) {
  // kfs sorted by frame; binary search (track QA must stay fast on long 4K events)
  let lo = 0, hi = kfs.length - 1;
  if (hi < 0 || f < kfs[0].frame || f > kfs[hi].frame) return null;
  while (lo <= hi) { const mid = (lo + hi) >> 1; const fm = kfs[mid].frame; if (fm === f) return kfs[mid].bbox; if (fm < f) lo = mid + 1; else hi = mid - 1; }
  const a = kfs[hi], b = kfs[lo];
  if (!a || !b) return null;
  const t = (f - a.frame) / (b.frame - a.frame), L = (p, q) => p + (q - p) * t;
  return { x: L(a.bbox.x, b.bbox.x), y: L(a.bbox.y, b.bbox.y), w: L(a.bbox.w, b.bbox.w), h: L(a.bbox.h, b.bbox.h) };
}
export function iou(a, b) {
  if (!a || !b) return 0;
  const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y), x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const uni = a.w * a.h + b.w * b.h - inter;
  return uni > 0 ? inter / uni : 0;
}
const center = b => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });

/** Default policy: a human decision at least every 2 s of source frames, jumps > 15% of frame, crossing IoU > 0.05. */
export function trackPolicy(content, fps) {
  const p = content?.track_qa_policy || {};
  const def = Math.max(1, Math.round((fps || 30) * 2));
  return {
    max_gap_frames: isInt(p.max_gap_frames) && p.max_gap_frames > 0 ? p.max_gap_frames : def,
    jump_threshold: finite(p.jump_threshold) && p.jump_threshold > 0 ? p.jump_threshold : 0.15,
    crossing_iou: finite(p.crossing_iou) && p.crossing_iou > 0 ? p.crossing_iou : 0.05,
  };
}

/** Required checkpoints for a segment's track with the reason each is required. */
export function requiredCheckpoints(content, seg, policy) {
  const kfs = content.keyframes.filter(k => k.segment_id === seg.id).sort((a, b) => a.frame - b.frame);
  const out = new Map();
  const add = (f, why) => { if (isInt(f) && f >= seg.start_frame && f < seg.end_frame) out.set(f, [...(out.get(f) || []), why]); };
  if (!kfs.length) return { checkpoints: [], keyframes: kfs };
  add(kfs[0].frame, 'start');
  add(kfs[kfs.length - 1].frame, 'end');
  const mid = Math.round((kfs[0].frame + kfs[kfs.length - 1].frame) / 2);
  add(kfs.reduce((best, k) => (Math.abs(k.frame - mid) < Math.abs(best.frame - mid) ? k : best), kfs[0]).frame, 'middle');
  for (const f of seg.key_moments?.inflection_frames || []) if (interpAt(kfs, f)) add(f, 'movement');
  for (const k of kfs) if (k.visibility && k.visibility !== 'visible') add(k.frame, `visibility_${k.visibility}`);
  for (let i = 1; i < kfs.length; i++) {
    const a = center(kfs[i - 1].bbox), b = center(kfs[i].bbox);
    if (Math.hypot(a.x - b.x, a.y - b.y) > policy.jump_threshold) { add(kfs[i - 1].frame, 'large_jump'); add(kfs[i].frame, 'large_jump'); }
  }
  // Crossings / hand-off risk: another segment's track overlaps this one in time and space.
  const crossings = [];
  for (const o of content.segments) {
    if (o.id === seg.id || o.athlete_id === seg.athlete_id && o.athlete_id != null) continue;
    const okfs = content.keyframes.filter(k => k.segment_id === o.id).sort((a, b) => a.frame - b.frame);
    if (!okfs.length) continue;
    const lo = Math.max(kfs[0].frame, okfs[0].frame), hi = Math.min(kfs[kfs.length - 1].frame, okfs[okfs.length - 1].frame);
    let inRun = false;
    const stepF = Math.max(1, Math.ceil((hi - lo + 1) / 2000));          // bounded work per pair: exact for spans <= 2000 frames, otherwise sampled every stepF frames
    for (let f = lo; f <= hi; f += stepF) {
      const hit = iou(interpAt(kfs, f), interpAt(okfs, f)) > policy.crossing_iou;
      if (hit && !inRun) { add(f, 'crossing'); crossings.push({ frame: f, other_segment_id: o.id }); }
      if (!hit && inRun) add(f, 'crossing_exit');
      inRun = hit;
    }
  }
  return { checkpoints: [...out].sort((a, b) => a[0] - b[0]).map(([frame, reasons]) => ({ frame, reasons })), keyframes: kfs, crossings };
}

/** Derived per-segment track QA summary. Honest by construction: partial evidence is never reported as verified. */
export function segmentTrackQa(content, seg, fps) {
  const policy = trackPolicy(content, fps);
  const { checkpoints, keyframes, crossings = [] } = requiredCheckpoints(content, seg, policy);
  const latest = latestByFrame((content.box_verifications || []).filter(v => v.segment_id === seg.id));
  const kfAt = new Map(keyframes.map(k => [k.frame, k]));
  const decisions = [];
  for (const v of latest.values()) {
    let st = v.status ?? 'unreviewed';
    const k = kfAt.get(v.frame);
    // Defensive (documents are validated on save): a positive decision that no longer matches the geometry or performer is stale.
    if (POSITIVE.has(st) && (!k || !boxEq(k.bbox, v.bbox) || v.athlete_id !== seg.athlete_id)) st = 'stale';
    decisions.push({ frame: v.frame, status: st, by: v.verified_by, at: v.verified_at });
  }
  decisions.sort((a, b) => a.frame - b.frame);
  const resolved = decisions.filter(d => DECIDED.has(d.status) && d.status !== 'wrong_performer');
  const positive = decisions.filter(d => POSITIVE.has(d.status));
  const wrong = decisions.filter(d => d.status === 'wrong_performer');
  const decidedFrames = new Set(resolved.map(d => d.frame));
  const cp = checkpoints.map(c => ({ ...c, decision: decisions.find(d => d.frame === c.frame)?.status ?? 'unreviewed' }));
  // A checkpoint is satisfied only by a decision that answers its question: identity risk points (crossing, jump,
  // movement, start/middle/end) need a POSITIVE decision; visibility checkpoints may also be answered 'occluded'.
  // 'Cannot determine' never satisfies a checkpoint of a track claimed as verified.
  const satisfies = c => { const d = decisions.find(x => x.frame === c.frame)?.status; return POSITIVE.has(d) || (d === 'occluded' && c.reasons.every(r => r.startsWith('visibility_'))); };
  const missing = cp.filter(c => !satisfies(c));
  const unresolvedCheckpoints = cp.filter(c => !decidedFrames.has(c.frame));
  let maxGap = null;
  if (keyframes.length) {
    const fs = [...decidedFrames].sort((a, b) => a - b);
    const lo = keyframes[0].frame, hi = keyframes[keyframes.length - 1].frame;
    const pts = [lo - 1, ...fs.filter(f => f >= lo && f <= hi), hi + 1];
    maxGap = 0; for (let i = 1; i < pts.length; i++) maxGap = Math.max(maxGap, pts[i] - pts[i - 1] - 1);
  }
  let status;
  if (wrong.length) status = 'needs_correction';
  else if (!keyframes.length) status = 'not_checked';
  else if (!decisions.some(d => DECIDED.has(d.status))) status = 'not_checked';
  else if (!positive.length && resolved.length && !unresolvedCheckpoints.length) status = 'cannot_determine';
  // A track needs at least two distinct human-checked positive frames; a single checked frame never verifies a track.
  else if (new Set(positive.map(d => d.frame)).size >= 2 && keyframes.length >= 2 && !missing.length && maxGap <= policy.max_gap_frames && !decisions.some(d => d.status === 'stale')) status = 'verified_in_checked_range';
  else status = 'partially_checked';
  return {
    segment_id: seg.id,
    status,
    has_boxes: keyframes.length > 0,
    box_frames: keyframes.length,
    interpolated_frames: keyframes.filter(k => k.origin === 'interpolated').length,
    checked_frames: resolved.length,
    verified_frames: positive.length,
    needs_correction_frames: wrong.map(d => d.frame),
    stale_frames: decisions.filter(d => d.status === 'stale').map(d => d.frame),
    checked_range: resolved.length ? [resolved[0].frame, resolved[resolved.length - 1].frame] : null,
    // Share of the EVENT (not of the box track) lying between the first and last human-checked frames.
    event_span_checked_ratio: resolved.length ? (resolved[resolved.length - 1].frame - resolved[0].frame + 1) / Math.max(1, seg.end_frame - seg.start_frame) : 0,
    required_checkpoints: cp,
    missing_checkpoints: missing.map(c => c.frame),
    crossings,
    max_unchecked_gap: maxGap,
    policy,
  };
}

export function trackQaSummary(content, fps) {
  return (content.segments || []).map(s => segmentTrackQa(content, s, fps));
}

/**
 * Approval by exception (operator principle: mark only what is wrong). For each event box, what an approval does:
 *  - to_verify:        a box of an event with a known performer, inside the watched part, visible, with no decision
 *                      (or whose earlier decision was invalidated) -> recorded as verified_correct, method 'exception_review'
 *  - already_verified: a bound positive decision exists (kept, not duplicated)
 *  - marked:           the operator marked it (✕ wrong performer / ◌ hidden / indeterminate) -> never verified
 *  - not_checked:      outside the watched part, no performer, or not visible -> left unreviewed
 * `events_checked`: events whose whole span was watched.
 */
const HIDDEN = new Set(['occluded', 'not_visible']);
function classifyBoxes(c) {
  const segs = new Map((c.segments ?? []).map(s => [s.id, s]));
  const ranges = c.reviewed_ranges ?? [];
  const watched = f => ranges.some(r => f >= r.start_frame && f < r.end_frame);
  const latest = latestByFrame(c.box_verifications);
  const out = { to_verify: [], already_verified: 0, marked: 0, not_checked: 0 };
  for (const k of c.keyframes ?? []) {
    const s = segs.get(k.segment_id); if (!s) continue;
    const v = latest.get(`${k.segment_id}:${k.frame}`), st = v?.status ?? 'unreviewed';
    if (POSITIVE.has(st) && boxEq(v.bbox, k.bbox)) out.already_verified++;
    else if (st !== 'unreviewed') out.marked++;
    else if (!s.athlete_id || !watched(k.frame) || HIDDEN.has(k.visibility) || !validBox(k.bbox)) out.not_checked++;
    else out.to_verify.push({ s, k });
  }
  const spanWatched = s => { for (let f = s.start_frame; f < s.end_frame; f++) if (!watched(f)) return false; return true; };
  out.events_checked = (c.segments ?? []).filter(spanWatched).length;
  out.events = (c.segments ?? []).length;
  return out;
}
export function approvalPreview(c) {
  const x = classifyBoxes(c);
  return { to_verify: x.to_verify.length, already_verified: x.already_verified, marked: x.marked, not_checked: x.not_checked, events_checked: x.events_checked, events: x.events };
}
/** Records the exception acceptance into `c` (mutates). Idempotent: a box already decided is never decided again. */
export function applyExceptionAcceptance(c, { author = 'operator', at = new Date().toISOString() } = {}) {
  const { to_verify } = classifyBoxes(c);
  if (!to_verify.length) return 0;
  c.box_verifications = Array.isArray(c.box_verifications) ? c.box_verifications : [];
  const latest = latestByFrame(c.box_verifications);
  for (const { s, k } of to_verify) {
    const prev = latest.get(`${k.segment_id}:${k.frame}`);
    const t = prev && ts(prev.verified_at) >= ts(at) ? new Date(ts(prev.verified_at) + 1).toISOString() : at;
    c.box_verifications.push({ segment_id: s.id, frame: k.frame, status: 'verified_correct', athlete_id: s.athlete_id, bbox: { ...k.bbox },
      verified_by: author, verified_at: t, method: 'exception_review' });
    k.verification_status = 'verified_correct';
  }
  return to_verify.length;
}
/** The boxes a training pipeline may use from an approved revision: latest decision positive and bound to this geometry. */
export function verifiedBoxes(c) {
  const segs = new Map((c.segments ?? []).map(s => [s.id, s]));
  const latest = latestByFrame(c.box_verifications);
  const out = [];
  for (const k of c.keyframes ?? []) {
    const s = segs.get(k.segment_id), v = latest.get(`${k.segment_id}:${k.frame}`);
    if (!s || !v || !POSITIVE.has(v.status) || !boxEq(v.bbox, k.bbox) || v.athlete_id !== s.athlete_id) continue;
    out.push({ segment_id: s.id, frame: k.frame, bbox: { ...k.bbox }, athlete_id: s.athlete_id, event_type: s.event_type, method: v.method ?? 'per_frame' });
  }
  return out.sort((a, b) => a.frame - b.frame);
}
