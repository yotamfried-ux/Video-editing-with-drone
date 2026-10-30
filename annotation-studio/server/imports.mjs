// Importers for the pipeline's exported evidence: `edl/v1` (how outputs were rendered) and `predictions/v1`
// (what the pipeline detected/selected/rejected). Both are validated, hash-checked against the catalog, and stored
// immutably with their digests. Nothing here talks to the pipeline or reads pipeline credentials.
import { ApiError } from './errors.mjs';
import { validateEdl, storeEdl } from './edl.mjs';
import { digestOf, latestRevision } from './annotations.mjs';
import { importPredictions } from './evaluate.mjs';

const SHA = /^[0-9a-f]{64}$/;

export function sourceBySha(db, sha) { return db.prepare('select * from sources where sha256=? order by created_at limit 1').get(sha); }

export function edlShas(edl) {
  const set = new Set(edl.shots.map(s => s.source_sha256 ?? edl.source_sha256).filter(h => SHA.test(h ?? '')));
  return [...set].sort();
}

/** GT lookup for an EDL: latest APPROVED revision per source sha (drafts are never used for evaluation). */
export function gtBySha(db, edl) {
  const out = { bySha: {}, revisions: {}, unresolved: [] };
  for (const sha of edlShas(edl)) {
    const src = sourceBySha(db, sha);
    const rev = src && latestRevision(db, src.id);
    if (!src) out.unresolved.push({ sha, reason: 'source_not_in_catalog' });
    else if (!rev) out.unresolved.push({ sha, reason: 'no_approved_revision', source_id: src.id });
    else { out.bySha[sha] = JSON.parse(rev.content); out.revisions[sha] = { id: rev.id, seq: rev.seq, source_id: src.id }; }
  }
  return out;
}

export function importEdl(db, edl) {
  validateEdl(edl);
  const shas = edlShas(edl);
  const resolved = shas.map(h => sourceBySha(db, h)).filter(Boolean);
  const unresolved = shas.filter(h => !sourceBySha(db, h));
  const digest = digestOf(edl);
  const existing = db.prepare('select id from edl_records where output_id=? and digest=?').get(edl.output_id, digest);
  if (existing) return { id: existing.id, duplicate: true, unresolved_sources: unresolved };
  const { id } = storeEdl(db, edl, resolved.length === 1 && !unresolved.length ? resolved[0].id : null);
  return { id, duplicate: false, unresolved_sources: unresolved, sources: resolved.map(s => s.id) };
}

/** predictions/v1 -> internal prediction record (selected events are predictions; rejected ones are diagnostics only). */
export function importPipelinePredictions(db, v1) {
  if (v1?.schema !== 'predictions/v1' || !Array.isArray(v1.sources)) throw new ApiError('INVALID_INPUT', 'predictions/v1 expected');
  for (const k of ['run_id', 'pipeline_commit']) {
    if (!v1[k] || v1[k] === 'unknown') throw new ApiError('INVALID_INPUT', `traceability: ${k} is required (run and code commit must be known)`);
  }
  const unmatched = [], sources = [];
  for (const s of v1.sources) {
    if (!SHA.test(s.source_sha256 ?? '') || !Array.isArray(s.events)) throw new ApiError('INVALID_INPUT', 'bad source entry');
    const cat = sourceBySha(db, s.source_sha256);
    if (!cat) unmatched.push(s.source_sha256);
    const fps = cat ? cat.fps_num / cat.fps_den : s.fps;
    const frames = e => {
      if (Number.isInteger(e.start_frame) && Number.isInteger(e.end_frame)) return [e.start_frame, e.end_frame];
      if (!fps) throw new ApiError('INVALID_INPUT', `cannot convert seconds to frames for ${s.source_sha256.slice(0, 8)} (fps unknown)`);
      return [Math.floor(e.start_sec * fps + 1e-6), Math.ceil(e.end_sec * fps - 1e-6)];
    };
    const events = [], rejected = [];
    for (const e of s.events) {
      const [start_frame, end_frame] = frames(e);
      if (!(end_frame > start_frame)) throw new ApiError('INVALID_INTERVAL');
      if (e.decision === 'selected') events.push({ start_frame, end_frame, athlete_key: e.athlete_key ?? null, candidate_id: e.candidate_id, event_type: e.event_type, score: e.score, outputs: e.outputs });
      else rejected.push({ start_frame, end_frame, reason: e.reason ?? 'unspecified', candidate_id: e.candidate_id });
    }
    sources.push({ source_sha256: s.source_sha256, source_video: s.source_video, events, rejected, tracks: s.tracks ?? [] });
  }
  const payload = { run_id: v1.run_id, pipeline_version: String(v1.pipeline_commit).slice(0, 12), sources };
  const digest = digestOf({ ...payload, export_digest: v1.digest });
  const dup = db.prepare('select id from pipeline_predictions where run_id=? and pipeline_version=?').get(payload.run_id, payload.pipeline_version);
  if (dup) return { id: dup.id, duplicate: true, unmatched_sources: unmatched };
  const out = importPredictions(db, { ...payload, extra: { pipeline_commit: v1.pipeline_commit, export_digest: v1.digest, export_schema: v1.schema, unmatched_sources: unmatched, outputs: v1.outputs ?? [], inputs: v1.inputs } });
  return { ...out, duplicate: false, unmatched_sources: unmatched };
}
