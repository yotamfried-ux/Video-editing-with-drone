// Ingestion: hash -> dedup by content -> archive+verify -> register -> derivatives.
// Identity is (sha256, byte_size). Paths are only ever recorded as observed locations.
import { statSync, readdirSync, existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { now, tx, audit } from './db.mjs';
import { sha256File } from './archive.mjs';
import { probe, makeThumb, makeProxy } from './media.mjs';

export const VIDEO_EXT = new Set(['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mts', '.mxf', '.webm']);
// Generated artifacts are never originals (spec §4).
export const DERIVATIVE_PREFIXES = ['review/', 'approved/', 'previews/', 'pending_payment/'];
export const ORIGINAL_PREFIXES = ['raw/', 'processed/', 'legacy/', 'uploads/'];

export class IngestError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

export function classifyKey(key) {
  const k = key.replace(/\\/g, '/').replace(/^\/+/, '');
  if (DERIVATIVE_PREFIXES.some(p => k.startsWith(p))) return 'derivative';
  return 'original';
}

export function ensureBatch(ctx, label, id = randomUUID()) {
  const row = ctx.db.prepare('select id from upload_batches where label=?').get(label);
  if (row) return row.id;
  ctx.db.prepare('insert into upload_batches(id,label,created_at) values(?,?,?)').run(id, label, now());
  return id;
}

function recordOccurrence(ctx, sourceId, batchId, name, key) {
  const t = now();
  ctx.db.prepare('insert or ignore into upload_occurrences(source_id,batch_id,original_name,location_key,created_at) values(?,?,?,?,?)')
    .run(sourceId, batchId, name, key, t);
  const loc = ctx.db.prepare("select id from source_locations where source_id=? and key=? and kind='operational'").get(sourceId, key);
  if (loc) ctx.db.prepare('update source_locations set active=1, observed_at=? where id=?').run(t, loc.id);
  else ctx.db.prepare("insert into source_locations(source_id,provider,bucket,key,kind,observed_at,active) values(?,?,?,?,'operational',?,1)")
    .run(sourceId, 'local-fs', null, key, t);
}

async function archiveAndDerive(ctx, src, filePath) {
  try {
    const key = await ctx.archive.put(filePath, src.sha256, src.byte_size);
    tx(ctx.db, () => {
      ctx.db.prepare("update sources set ingest_state='ready', archive_key=?, archive_verified_at=?, archive_error=null where id=?")
        .run(key, now(), src.id);
      const have = ctx.db.prepare("select 1 from source_locations where source_id=? and kind='archive' and key=?").get(src.id, key);
      if (!have) ctx.db.prepare("insert into source_locations(source_id,provider,bucket,key,kind,observed_at,active,verified_sha256) values(?,?,?,?,'archive',?,1,?)")
        .run(src.id, 'local-archive', null, key, now(), src.sha256);
      audit(ctx.db, 'system', 'archive_verified', src.id, { key });
    });
  } catch (e) {
    ctx.db.prepare("update sources set ingest_state='archive_error', archive_error=? where id=?").run(String(e.message), src.id);
    audit(ctx.db, 'system', 'archive_failed', src.id, { error: e.message });
    return { ok: false, error: e.message };
  }
  // Derivatives are best-effort: a missing thumbnail must never block annotation.
  const archived = ctx.archive.pathFor(ctx.db.prepare('select archive_key k from sources where id=?').get(src.id).k);
  const m = ctx.db.prepare('select fps_num,fps_den from sources where id=?').get(src.id);
  const dir = path.join(ctx.cacheDir, src.id);
  try {
    const t = path.join(dir, 'thumb.jpg'); await makeThumb(archived, t);
    ctx.db.prepare('update sources set thumb_path=? where id=?').run(t, src.id);
  } catch (e) { audit(ctx.db, 'system', 'thumb_failed', src.id, { error: e.message }); }
  try {
    const p = path.join(dir, 'proxy.webm'); await makeProxy(archived, p, { fpsNum: m.fps_num, fpsDen: m.fps_den });
    ctx.db.prepare('update sources set proxy_path=? where id=?').run(p, src.id);
  } catch (e) { audit(ctx.db, 'system', 'proxy_failed', src.id, { error: e.message }); }
  return { ok: true };
}

/** Ingest one file. Idempotent: same bytes -> same source, new occurrence only. */
export async function ingestFile(ctx, { filePath, locationKey, batchId, originalName }) {
  const key = (locationKey ?? path.basename(filePath)).replace(/\\/g, '/');
  if (classifyKey(key) === 'derivative') throw new IngestError('NOT_ORIGINAL', `generated output prefix refused: ${key}`);
  if (!VIDEO_EXT.has(path.extname(filePath).toLowerCase())) throw new IngestError('NOT_VIDEO', `unsupported extension: ${filePath}`);
  const before = statSync(filePath);
  const sha = await sha256File(filePath);
  const after = statSync(filePath);
  // Partial/in-flight upload guard: bytes changed while hashing.
  if (before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
    throw new IngestError('INGEST_RETRYABLE', `file changed while hashing: ${filePath}`);
  }
  const name = originalName ?? path.basename(filePath);
  let src = ctx.db.prepare('select * from sources where sha256=? and byte_size=?').get(sha, after.size);
  let duplicate = true;
  if (!src) {
    duplicate = false;
    let meta;
    try { meta = await probe(filePath); }
    catch (e) { throw new IngestError(e.code || 'INGEST_RETRYABLE', `probe failed: ${e.message}`); }
    const id = randomUUID();
    ctx.db.prepare(`insert into sources(id,sha256,byte_size,display_name,session_key,codec,width,height,rotation,fps_num,fps_den,frame_count,duration_ms,captured_at,ingest_state,created_at)
      values(?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending_archive', ?)`)
      .run(id, sha, after.size, name, meta.captured_at ? meta.captured_at.slice(0, 10) : null, meta.codec, meta.width, meta.height, meta.rotation,
        meta.fps_num, meta.fps_den, meta.frame_count, meta.duration_ms, meta.captured_at, now());
    src = ctx.db.prepare('select * from sources where id=?').get(id);
    audit(ctx.db, 'system', 'source_registered', id, { sha256: sha });
  }
  tx(ctx.db, () => recordOccurrence(ctx, src.id, batchId, name, key));
  let archive = { ok: src.ingest_state === 'ready' };
  if (src.ingest_state !== 'ready') archive = await archiveAndDerive(ctx, src, filePath);
  return { sourceId: src.id, duplicate, archived: archive.ok, error: archive.error };
}

function walk(dir, base = dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, base, out);
    else if (VIDEO_EXT.has(path.extname(e.name).toLowerCase())) out.push({ abs: p, rel: path.relative(base, p).replace(/\\/g, '/') });
  }
  return out;
}

/**
 * Reconcile operational storage with the catalog. Discovers files whose events were lost,
 * retries failed jobs, repairs half-registered sources, and marks vanished operational
 * locations inactive. It never deletes or alters sources, archives, or annotations.
 */
export async function reconcile(ctx, { roots, batchLabel = `reconcile-${now().slice(0, 10)}`, deep = false }) {
  const batchId = ensureBatch(ctx, batchLabel);
  const report = { scanned: 0, ingested: 0, duplicates: 0, skipped: 0, refused: [], errors: [], repaired: 0, locations_deactivated: 0 };
  const seenKeys = new Set();
  for (const root of roots) {
    if (!existsSync(root.dir)) continue;
    for (const f of walk(root.dir)) {
      const key = `${root.prefix}${f.rel}`;
      if (classifyKey(key) === 'derivative') { report.refused.push(key); continue; }
      seenKeys.add(key);
      report.scanned++;
      const size = statSync(f.abs).size;
      const known = ctx.db.prepare(`select s.id, s.byte_size, s.ingest_state from source_locations l join sources s on s.id=l.source_id
        where l.key=? and l.kind='operational' and l.active=1`).get(key);
      if (!deep && known && known.byte_size === size && known.ingest_state === 'ready') { report.skipped++; continue; }
      const job = upsertJob(ctx, key, batchId);
      try {
        const r = await ingestFile(ctx, { filePath: f.abs, locationKey: key, batchId });
        finishJob(ctx, job, r.archived ? 'done' : 'failed', r.error, r.sourceId);
        if (!r.archived) report.errors.push({ key, error: r.error });
        else if (known) report.repaired++;
        else r.duplicate ? report.duplicates++ : report.ingested++;
      } catch (e) {
        finishJob(ctx, job, 'failed', `${e.code || 'ERR'}: ${e.message}`);
        report.errors.push({ key, error: `${e.code || 'ERR'}: ${e.message}` });
      }
    }
  }
  // Vanished operational files: deactivate the *location*; identity and archive stay.
  for (const l of ctx.db.prepare("select id,key from source_locations where kind='operational' and active=1").all()) {
    if (!seenKeys.has(l.key) && roots.some(r => l.key.startsWith(r.prefix))) {
      ctx.db.prepare('update source_locations set active=0 where id=?').run(l.id);
      report.locations_deactivated++;
    }
  }
  audit(ctx.db, 'operator', 'reconcile', null, report);
  return report;
}

function upsertJob(ctx, key, batchId) {
  const t = now();
  ctx.db.prepare(`insert into ingestion_jobs(origin_key,batch_id,state,attempts,created_at,updated_at) values(?,?,'running',1,?,?)
    on conflict(origin_key,batch_id) do update set state='running', attempts=ingestion_jobs.attempts+1, updated_at=excluded.updated_at`).run(key, batchId, t, t);
  return ctx.db.prepare('select id from ingestion_jobs where origin_key=? and batch_id=?').get(key, batchId).id;
}
function finishJob(ctx, id, state, error, sourceId) {
  ctx.db.prepare('update ingestion_jobs set state=?, error=?, source_id=?, updated_at=? where id=?')
    .run(state, error ?? null, sourceId ?? null, now(), id);
}

/** Integrity audit: re-hash every archived original. Failures are surfaced, never hidden. */
export async function verifyArchives(ctx) {
  const out = { checked: 0, ok: 0, failed: [] };
  for (const s of ctx.db.prepare("select id,sha256,byte_size,archive_key from sources where archive_key is not null").all()) {
    out.checked++;
    const r = await ctx.archive.verify(s.archive_key, s.sha256, s.byte_size);
    if (r.ok) { out.ok++; ctx.db.prepare("update sources set archive_verified_at=?, ingest_state=case when ingest_state='archive_error' then 'ready' else ingest_state end where id=?").run(now(), s.id); }
    else {
      out.failed.push({ id: s.id, reason: r.reason });
      ctx.db.prepare("update sources set ingest_state='archive_error', archive_error=? where id=?").run(`verify:${r.reason}`, s.id);
    }
  }
  audit(ctx.db, 'operator', 'verify_archives', null, out);
  return out;
}
