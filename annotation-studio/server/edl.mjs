// Editing-quality evaluation (M5). Maps ground-truth source boxes through the render's Edit
// Decision List into output pixels. No EDL => NOT_EVALUABLE; never a guessed pass.
import { randomUUID } from 'node:crypto';
import { now } from './db.mjs';
import { ApiError } from './errors.mjs';
import { digestOf } from './annotations.mjs';

export const EDITING_EVALUATOR_VERSION = 'edit-eval-1.0.0';
export const DEFAULT_THRESHOLDS = {
  safe_margin: 0.04,          // fraction of output size
  centering_error_max: 0.15,  // normalized euclidean
  crop_jump_per_frame: 0.08,  // crop-center displacement / crop width, per frame
  crop_jerk_max: 0.02,
};

export function validateEdl(e) {
  const bad = m => { throw Object.assign(new ApiError('EDL_UNVERIFIED', m), { he: m }); };
  if (!e || e.schema !== 'edl/v1') bad('EDL schema must be edl/v1');
  for (const k of ['output_id', 'run_id']) if (!e[k]) bad(`missing ${k}`);
  if (!['contain', 'tracked_crop', 'pad', 'mixed'].includes(e.mode)) bad('invalid mode');
  const dim = d => d && d.width > 0 && d.height > 0;
  if (!dim(e.output) || !(e.output.fps > 0)) bad('invalid output dimensions');
  if (![0, 90, 180, 270].includes(e.rotation ?? 0)) bad('invalid rotation');
  if (!Array.isArray(e.shots) || !e.shots.length) bad('no shots');
  const multi = e.shots.some(s => s.source_sha256 && s.source_sha256 !== e.source_sha256);
  if (!multi && !dim(e.source)) bad('invalid source dimensions');
  if (!multi && !/^[0-9a-f]{64}$/.test(e.source_sha256 ?? '')) bad('missing source_sha256');
  let prev = -1;
  for (const s of e.shots) {
    if (!(s.out_end > s.out_start) || s.out_start <= prev) bad('shots must be ordered and non-empty');
    prev = s.out_end - 1;
    if (s.source_sha256 && !/^[0-9a-f]{64}$/.test(s.source_sha256)) bad('invalid shot source_sha256');
    if (s.source && !dim(s.source)) bad('invalid shot source dimensions');
    if (s.mode && !['contain', 'tracked_crop', 'pad'].includes(s.mode)) bad('invalid shot mode');
    for (const c of [s.crop_start, s.crop_end ?? s.crop_start]) if (!c || !(c.w > 0) || !(c.h > 0)) bad('invalid crop');
    if (s.keyframes) {
      let last = -1;
      for (const k of s.keyframes) {
        if (!Number.isInteger(k.out_frame) || k.out_frame <= last || !k.crop || !(k.crop.w > 0) || !(k.crop.h > 0)) bad('invalid keyframes');
        last = k.out_frame;
      }
    }
  }
  for (const bl of e.blends ?? []) if (!(bl.out_end > bl.out_start)) bad('invalid blend');
  return true;
}

export const shotMode = (edl, shot) => shot.mode ?? edl.mode;
export const shotSource = (edl, shot) => ({ sha: shot.source_sha256 ?? edl.source_sha256, dims: shot.source ?? edl.source });
export const inBlend = (edl, f) => (edl.blends ?? []).some(b => f >= b.out_start && f < b.out_end);

/** Crop at output frame f inside a shot: piecewise-linear over `keyframes`, else linear crop_start -> crop_end. */
export function shotAt(edl, f) {
  const s = edl.shots.find(x => f >= x.out_start && f < x.out_end);
  if (!s) return null;
  let crop;
  if (s.keyframes?.length) {
    const ks = s.keyframes;
    let i = 0; while (i + 1 < ks.length && ks[i + 1].out_frame <= f) i++;
    const a = ks[i], b = ks[i + 1] ?? a;
    const t = a === b || b.out_frame === a.out_frame ? 0 : Math.min(1, Math.max(0, (f - a.out_frame) / (b.out_frame - a.out_frame)));
    const L = (x, y) => x + (y - x) * t;
    crop = { cx: L(a.crop.cx, b.crop.cx), cy: L(a.crop.cy, b.crop.cy), w: L(a.crop.w, b.crop.w), h: L(a.crop.h, b.crop.h) };
  } else {
    const span = s.out_end - s.out_start - 1;
    const t = span > 0 ? (f - s.out_start) / span : 0;
    const a = s.crop_start, b = s.crop_end ?? s.crop_start;
    const L = (x, y) => x + (y - x) * t;
    crop = { cx: L(a.cx, b.cx), cy: L(a.cy, b.cy), w: L(a.w, b.w), h: L(a.h, b.h) };
  }
  return { shot: s, crop, src_frame: Math.round(s.src_start + (f - s.out_start) * (s.speed ?? 1)) };
}

/** Source pixel point -> output pixel point for a crop (uniform scale, optional rotation, centered). */
export function makeTransform(edl, crop) {
  const rot = edl.rotation ?? 0;
  const swap = rot === 90 || rot === 270;
  const ew = swap ? crop.h : crop.w, eh = swap ? crop.w : crop.h;
  const s = Math.min(edl.output.width / ew, edl.output.height / eh);
  const th = rot * Math.PI / 180, c = Math.round(Math.cos(th)), sn = Math.round(Math.sin(th));
  const pt = (x, y) => {
    const dx = (x - crop.cx) * s, dy = (y - crop.cy) * s;
    return [dx * c - dy * sn + edl.output.width / 2, dx * sn + dy * c + edl.output.height / 2];
  };
  return { scale: s, pt };
}

const aabb = pts => ({ x1: Math.min(...pts.map(p => p[0])), y1: Math.min(...pts.map(p => p[1])),
  x2: Math.max(...pts.map(p => p[0])), y2: Math.max(...pts.map(p => p[1])) });
const area = r => Math.max(0, r.x2 - r.x1) * Math.max(0, r.y2 - r.y1);
const inter = (a, b) => ({ x1: Math.max(a.x1, b.x1), y1: Math.max(a.y1, b.y1), x2: Math.min(a.x2, b.x2), y2: Math.min(a.y2, b.y2) });

/** Normalized source bbox {x,y,w,h} -> output-pixel AABB, plus the displayed content region. */
export function sourceBoxToOutput(edl, crop, bbox, dims = edl.source) {
  const { width: W, height: H } = dims;
  const tf = makeTransform(edl, crop);
  const box = aabb([[bbox.x * W, bbox.y * H], [(bbox.x + bbox.w) * W, bbox.y * H], [bbox.x * W, (bbox.y + bbox.h) * H], [(bbox.x + bbox.w) * W, (bbox.y + bbox.h) * H]].map(([x, y]) => tf.pt(x, y)));
  const cropRect = { x1: Math.max(0, crop.cx - crop.w / 2), y1: Math.max(0, crop.cy - crop.h / 2), x2: Math.min(W, crop.cx + crop.w / 2), y2: Math.min(H, crop.cy + crop.h / 2) };
  const region = aabb([[cropRect.x1, cropRect.y1], [cropRect.x2, cropRect.y1], [cropRect.x1, cropRect.y2], [cropRect.x2, cropRect.y2]].map(([x, y]) => tf.pt(x, y)));
  return { box, region, scale: tf.scale };
}

function interpBox(kfs, frame) {
  const ks = kfs.slice().sort((a, b) => a.frame - b.frame);
  if (!ks.length || frame < ks[0].frame || frame > ks[ks.length - 1].frame) return null;
  let i = 0; while (i + 1 < ks.length && ks[i + 1].frame <= frame) i++;
  const a = ks[i], b = ks[i + 1] ?? a;
  if (a.frame === frame || a === b) return { bbox: a.bbox, origin: a.frame === frame ? a.origin : 'interpolated', visibility: a.visibility };
  const t = (frame - a.frame) / (b.frame - a.frame), L = (x, y) => x + (y - x) * t;
  return { bbox: { x: L(a.bbox.x, b.bbox.x), y: L(a.bbox.y, b.bbox.y), w: L(a.bbox.w, b.bbox.w), h: L(a.bbox.h, b.bbox.h) }, origin: 'interpolated', visibility: a.visibility };
}

const q = (arr, p) => { if (!arr.length) return null; const s = arr.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.ceil(p * s.length) - 1)]; };
const r6 = v => v == null ? null : Math.round(v * 1e6) / 1e6;

/**
 * Evaluate one rendered output against approved ground truth.
 * @param edl EDL or null  @param gt approved revision content  @param opts {thresholds}
 */
/** `gtSpec` = one approved-revision content, or `{ bySha: { <sha256>: content } }` for multi-source reels. */
const gtFor = (spec, sha) => spec?.bySha ? spec.bySha[sha] : spec;

export function evaluateEditing(edl, gtSpec, opts = {}) {
  const th = { ...DEFAULT_THRESHOLDS, ...(opts.thresholds ?? {}) };
  const base = { evaluator_version: EDITING_EVALUATOR_VERSION, thresholds: th };
  if (!edl) return { ...base, status: 'NOT_EVALUABLE', reason: 'EDL_UNVERIFIED', mapping: 'unverified_mapping' };
  validateEdl(edl);
  if (edl.mapping === 'visual_match') return { ...base, status: 'NOT_EVALUABLE', reason: 'EDL_UNVERIFIED', mapping: 'unverified_mapping' };

  const centerRows = [], timeline = [], rows = [];
  let evaluated = 0, visible = 0, partial = 0, missing = 0, edgeViol = 0, skippedUnreviewed = 0, notScored = 0, blendFrames = 0, unresolvedFrames = 0;
  const total = edl.shots[edl.shots.length - 1].out_end;
  for (let f = 0; f < total; f++) {
    const at = shotAt(edl, f);
    if (!at) continue;
    // Cross-dissolve frames mix two clips: never attributed to either (no approximate evidence).
    if (inBlend(edl, f)) { blendFrames++; continue; }
    const { sha, dims } = shotSource(edl, at.shot);
    const gt = gtFor(gtSpec, sha);
    if (!gt) { unresolvedFrames++; continue; }
    const mode = shotMode(edl, at.shot);
    const seg = gt.segments.find(s => s.decision === 'include' && at.src_frame >= s.start_frame && at.src_frame < s.end_frame);
    const reviewed = gt.reviewed_ranges.some(r => at.src_frame >= r.start_frame && at.src_frame < r.end_frame);
    const kb = seg && interpBox(gt.keyframes.filter(k => k.segment_id === seg.id), at.src_frame);
    if (!seg || !kb || !reviewed || kb.visibility === 'occluded' || kb.visibility === 'not_visible') { skippedUnreviewed++; continue; }
    evaluated++;
    const { box, region } = sourceBoxToOutput(edl, at.crop, kb.bbox, dims);
    const W = edl.output.width, H = edl.output.height;
    const bArea = area(box);
    const vis = bArea > 0 ? area(inter(inter(box, region), { x1: 0, y1: 0, x2: W, y2: H })) / bArea : 0;
    const ev = { out_frame: f, src_frame: at.src_frame, segment_id: seg.id };
    if (vis <= 1e-6) { missing++; timeline.push({ ...ev, type: 'missing_surfer', evidence_origin: kb.origin }); }
    else if (vis < 0.999) { partial++; timeline.push({ ...ev, type: 'partial_clipping', visible_fraction: r6(vis), evidence_origin: kb.origin }); }
    else visible++;
    const m = th.safe_margin;
    const safe = { x1: Math.max(region.x1, 0) + m * W, y1: Math.max(region.y1, 0) + m * H, x2: Math.min(region.x2, W) - m * W, y2: Math.min(region.y2, H) - m * H };
    const violates = vis > 0 && (box.x1 < safe.x1 || box.y1 < safe.y1 || box.x2 > safe.x2 || box.y2 > safe.y2) && mode === 'tracked_crop';
    if (violates && vis >= 0.999) { edgeViol++; timeline.push({ ...ev, type: 'edge_violation' }); }
    const cx = (box.x1 + box.x2) / 2 / W, cy = (box.y1 + box.y2) / 2 / H;
    // Target selection: contain is NOT penalised for off-centre; lead-room uses the operator target.
    let target = null;
    if (mode === 'tracked_crop') {
      if (seg.framing_mode === 'geometric_center') target = { x: 0.5, y: 0.5 };
      else if (seg.framing_mode === 'directional_lead_room' && seg.target) target = seg.target;
    }
    if (target) {
      const err = Math.hypot(cx - target.x, cy - target.y);
      centerRows.push(err);
      if (err > th.centering_error_max) timeline.push({ ...ev, type: 'centering_error', error: r6(err) });
    } else notScored++;
    // Identity: optional pipeline subject track in source coordinates.
    const st = (at.shot.subject_track ?? edl.subject_track)?.find(t => t.src_frame === at.src_frame);
    if (st) {
      const g = kb.bbox, s = st.bbox;
      const ix = Math.max(0, Math.min(g.x + g.w, s.x + s.w) - Math.max(g.x, s.x)), iy = Math.max(0, Math.min(g.y + g.h, s.y + s.h) - Math.max(g.y, s.y));
      const i = ix * iy, u = g.w * g.h + s.w * s.h - i;
      if (u > 0 && i / u < 0.1) timeline.push({ ...ev, type: 'wrong_surfer', iou: r6(i / u) });
    }
    rows.push({ f, crop: at.crop, shot: at.shot, mode });
  }
  // Smoothness within continuous shots only (cuts excluded).
  const jumps = [], jerk = [];
  for (const shot of edl.shots) {
    const pts = rows.filter(r => r.shot === shot);
    let v0 = null, a0 = null;
    for (let i = 1; i < pts.length; i++) {
      if (pts[i].f !== pts[i - 1].f + 1) { v0 = a0 = null; continue; }
      const vx = (pts[i].crop.cx - pts[i - 1].crop.cx) / pts[i].crop.w, vy = (pts[i].crop.cy - pts[i - 1].crop.cy) / pts[i].crop.w;
      const v = Math.hypot(vx, vy);
      if (v > th.crop_jump_per_frame) { jumps.push(v); timeline.push({ out_frame: pts[i].f, src_frame: shotAt(edl, pts[i].f).src_frame, type: 'crop_jump', velocity: r6(v) }); }
      if (v0 != null) { const a = v - v0; if (a0 != null) { const j = Math.abs(a - a0); jerk.push(j); } a0 = a; }
      v0 = v;
    }
  }
  timeline.sort((a, b) => a.out_frame - b.out_frame || (a.type < b.type ? -1 : 1));
  const frac = n => evaluated ? r6(n / evaluated) : null;
  const report = {
    ...base, status: evaluated ? 'EVALUATED' : 'NOT_EVALUABLE', reason: evaluated ? undefined : 'NO_REVIEWED_FRAMES',
    mapping: 'verified', mode: edl.mode, output_id: edl.output_id, run_id: edl.run_id,
    coverage: { output_frames: total, evaluated_frames: evaluated, unreviewed_or_unavailable: skippedUnreviewed, blend_frames: blendFrames,
      source_not_in_catalog_frames: unresolvedFrames, coverage_ratio: r6(evaluated / total) },
    visibility: { fully_visible: frac(visible), partially_clipped: frac(partial), missing: frac(missing) },
    edge_violation_share: frac(edgeViol),
    centering: centerRows.length ? { scored_frames: centerRows.length, median: r6(q(centerRows, 0.5)), p95: r6(q(centerRows, 0.95)), max: r6(Math.max(...centerRows)) }
      : { scored_frames: 0, note: edl.mode === 'contain' ? 'contain framing is not scored against centre' : edl.mode === 'mixed' ? 'no tracked-crop frame with an operator target' : 'no operator target selected' },
    not_centering_scored_frames: notScored,
    smoothness: { crop_jumps: jumps.length, max_jerk: jerk.length ? r6(Math.max(...jerk)) : 0, jerk_flags: jerk.filter(j => j > th.crop_jerk_max).length },
    errors: timeline,
  };
  return report;
}

export function storeEdl(db, edl, sourceId = null) {
  validateEdl(edl);
  const id = randomUUID();
  db.prepare('insert into edl_records(id,output_id,run_id,source_id,payload,digest,created_at) values(?,?,?,?,?,?,?)')
    .run(id, edl.output_id, edl.run_id, sourceId, JSON.stringify(edl), digestOf(edl), now());
  return { id };
}

/** Proposal only: a candidate crop window on the source. Never touches production output. */
export function proposeCrop({ source, bbox, mode = 'geometric_center', target = null, aspect = 9 / 16 }) {
  const W = source.width, H = source.height;
  const t = mode === 'geometric_center' ? { x: 0.5, y: 0.5 } : (target ?? { x: 0.5, y: 0.5 });
  const h = Math.min(H, W / aspect), w = h * aspect;
  const bcx = (bbox.x + bbox.w / 2) * W, bcy = (bbox.y + bbox.h / 2) * H;
  // choose crop so the box centre lands on target inside the crop, then clamp to the frame
  let cx = bcx - (t.x - 0.5) * w, cy = bcy - (t.y - 0.5) * h;
  cx = Math.min(W - w / 2, Math.max(w / 2, cx)); cy = Math.min(H - h / 2, Math.max(h / 2, cy));
  return { cx, cy, w, h, mode, target: t, status: 'proposal' };
}

/**
 * Per-output-frame evidence for the Editing Review screen: transformed ground-truth box, crop
 * region and visibility, only on reviewed frames and only with a verified EDL.
 */
export function frameEvidence(edl, gtSpec) {
  if (!edl || edl.mapping === 'visual_match') return { verified: false, frames: [] };
  validateEdl(edl);
  const W = edl.output.width, H = edl.output.height, frames = [];
  const total = edl.shots[edl.shots.length - 1].out_end;
  for (let f = 0; f < total; f++) {
    const at = shotAt(edl, f); if (!at) continue;
    const { sha, dims } = shotSource(edl, at.shot);
    const mode = shotMode(edl, at.shot);
    const base = { f, src: at.src_frame, sha, mode, crop: at.crop, cut: edl.shots.some(s => s.out_start === f && f > 0), blend: inBlend(edl, f) };
    const gt = gtFor(gtSpec, sha);
    if (!gt || base.blend) { frames.push({ ...base, reviewed: false }); continue; }
    const seg = gt.segments.find(s => s.decision === 'include' && at.src_frame >= s.start_frame && at.src_frame < s.end_frame);
    const kb = seg && interpBox(gt.keyframes.filter(k => k.segment_id === seg.id), at.src_frame);
    const reviewed = gt.reviewed_ranges.some(r => at.src_frame >= r.start_frame && at.src_frame < r.end_frame);
    if (!kb || !reviewed) { frames.push({ ...base, reviewed: false }); continue; }
    const { box, region } = sourceBoxToOutput(edl, at.crop, kb.bbox, dims);
    const ba = area(box);
    const vis = ba > 0 ? area(inter(inter(box, region), { x1: 0, y1: 0, x2: W, y2: H })) / ba : 0;
    let err = null, target = null;
    if (mode === 'tracked_crop') {
      target = seg.framing_mode === 'geometric_center' ? { x: 0.5, y: 0.5 } : seg.framing_mode === 'directional_lead_room' ? seg.target : null;
      if (target) err = Math.hypot((box.x1 + box.x2) / 2 / W - target.x, (box.y1 + box.y2) / 2 / H - target.y);
    }
    frames.push({ ...base, reviewed: true, segment_id: seg.id, origin: kb.origin, src_bbox: kb.bbox, framing_mode: seg.framing_mode ?? null, box, region, vis: r6(vis), err: r6(err), target });
  }
  return { verified: true, frames };
}
