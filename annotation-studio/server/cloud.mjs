// Cloud source catalog: SportReel's EXISTING source videos in Cloudflare R2, used in place (no re-upload, no copy).
//
// Safety model
//  * CloudBucket is READ-ONLY by construction: it only ever issues GET/HEAD requests and has no write/delete/copy
//    method at all. Give it an "Object Read only" R2 token and even a bug here cannot change the bucket.
//  * Credentials live in this server process only (closure-private); they are never sent to the browser. The browser
//    receives video bytes through the authenticated /media route, which supports Range requests for seeking.
//  * A cloud source is identified by sha256+byte_size like every other source. The SHA-256 comes from the durable
//    source_uploads record (computed by the pipeline) and is re-verified from the bytes by an explicit verify job;
//    approving Ground Truth requires that verification to have passed.
import { createHash, randomUUID } from 'node:crypto';
import { Readable } from 'node:stream';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { signRequest, sha256hex } from './sigv4.mjs';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { probe, makeThumb, makeProxy } from './media.mjs';

export class CloudError extends Error { constructor(code, message) { super(message); this.code = code; } }

export function cloudConfigFromEnv(env = process.env) {
  if (!env.STUDIO_CLOUD_R2_BUCKET) return null;                       // cloud mode is optional
  const need = n => { if (!env[n]) throw new CloudError('CLOUD_CONFIG', `${n} is not set`); return env[n]; };
  return {
    endpoint: env.STUDIO_CLOUD_R2_ENDPOINT || `https://${need('STUDIO_CLOUD_R2_ACCOUNT_ID')}.r2.cloudflarestorage.com`,
    bucket: env.STUDIO_CLOUD_R2_BUCKET,
    accessKeyId: need('STUDIO_CLOUD_R2_ACCESS_KEY_ID'),
    secretAccessKey: need('STUDIO_CLOUD_R2_SECRET_ACCESS_KEY'),
  };
}

const tag = (xml, name) => { const m = new RegExp(`<${name}>([^<]*)</${name}>`).exec(xml); return m ? m[1] : null; };
const unXml = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'");

export class CloudBucket {
  kind = 'cloud-r2-readonly';
  #sign;
  constructor({ endpoint, bucket, accessKeyId, secretAccessKey, region = 'auto', fetchImpl = fetch, retries = 3 }) {
    for (const [k, v] of Object.entries({ endpoint, bucket, accessKeyId, secretAccessKey })) if (!v) throw new CloudError('CLOUD_CONFIG', `${k} required`);
    const secret = { accessKeyId, secretAccessKey };                  // closure-private: never serialised or logged
    this.#sign = a => signRequest({ ...a, region, service: 's3', ...secret });
    this.endpoint = endpoint.replace(/\/+$/, ''); this.bucket = bucket; this.fetch = fetchImpl; this.retries = retries;
  }
  toJSON() { return { kind: this.kind, bucket: this.bucket }; }

  #url(key, query = '') { return `${this.endpoint}/${this.bucket}/${key.split('/').map(encodeURIComponent).join('/')}${query}`; }

  async #request(method, key, { query = '', headers = {}, expect = [200] } = {}) {
    if (method !== 'GET' && method !== 'HEAD') throw new CloudError('CLOUD_READ_ONLY', `refusing ${method}: the cloud catalog is read-only`);
    let last;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      const url = this.#url(key, query);
      const { _canonical, ...hdrs } = this.#sign({ method, url, headers, payloadHash: sha256hex('') });
      try {
        const res = await this.fetch(url, { method, headers: hdrs });
        if (expect.includes(res.status)) return res;
        await res.arrayBuffer().catch(() => {});
        const retriable = res.status >= 500 || res.status === 429;
        last = new CloudError(res.status === 404 ? 'CLOUD_NOT_FOUND' : res.status === 403 || res.status === 401 ? 'CLOUD_FORBIDDEN' : retriable ? 'CLOUD_RETRYABLE' : 'CLOUD_REJECTED',
          `cloud storage ${method} returned ${res.status}`);
        if (!retriable) throw last;
      } catch (e) {
        if (e instanceof CloudError && e.code !== 'CLOUD_RETRYABLE') throw e;
        last = e instanceof CloudError ? e : new CloudError('CLOUD_RETRYABLE', 'cloud storage request failed');
      }
      await new Promise(r => setTimeout(r, 20 * 2 ** attempt));
    }
    throw last;
  }

  /** @returns [{key,size,etag,lastModified}] for every object under the prefix. */
  async list(prefix) {
    const out = []; let token = '';
    do {
      const q = `?list-type=2&prefix=${encodeURIComponent(prefix)}${token ? `&continuation-token=${encodeURIComponent(token)}` : ''}`;
      const xml = await (await this.#request('GET', '', { query: q })).text();
      for (const block of xml.split('<Contents>').slice(1)) {
        const key = tag(block, 'Key');
        if (key && !key.endsWith('/')) out.push({ key: unXml(key), size: Number(tag(block, 'Size')), etag: (tag(block, 'ETag') ?? '').replace(/&quot;|"/g, '') || null, lastModified: tag(block, 'LastModified') });
      }
      token = tag(xml, 'NextContinuationToken') ?? '';
    } while (token);
    return out;
  }

  async head(key) {
    try {
      const r = await this.#request('HEAD', key);
      return { size: Number(r.headers.get('content-length')), etag: (r.headers.get('etag') ?? '').replace(/"/g, '') || null, lastModified: r.headers.get('last-modified'), contentType: r.headers.get('content-type') };
    } catch (e) { if (e.code === 'CLOUD_NOT_FOUND') return null; throw e; }
  }
  async size(key) { return (await this.head(key))?.size ?? null; }

  /** Streams the object, optionally a byte range (seeking). */
  async open(key, { start, end } = {}) {
    const headers = start != null ? { range: `bytes=${start}-${end ?? ''}` } : {};
    const r = await this.#request('GET', key, { headers, expect: [200, 206] });
    return Readable.fromWeb(r.body);
  }

  async getText(key, maxBytes = 1 << 20) {
    const r = await this.#request('GET', key);
    const buf = Buffer.from(await r.arrayBuffer());
    if (buf.length > maxBytes) throw new CloudError('CLOUD_REJECTED', 'object too large to read as text');
    return buf.toString('utf8');
  }

  /** Streams the whole object and returns its SHA-256 (read-only; used by the verify job). */
  async sha256(key) {
    const h = createHash('sha256');
    for await (const chunk of await this.open(key)) h.update(chunk);
    return h.digest('hex');
  }
}

// ---------------------------------------------------------------------------------------------------------------
const VIDEO_EXT = new Set(['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mts', '.mxf']);
const isVideo = key => VIDEO_EXT.has(path.extname(key).toLowerCase());
const baseName = key => key.slice(key.lastIndexOf('/') + 1);
export const SOURCE_PREFIXES = ['raw/', 'processed/'];                 // originals only; review/ approved/ previews/ are outputs
const STATE_PREFIX = 'metadata/source_state/';

/** Durable upload records exported from Supabase (source_uploads rows) or from raw_recovery.py's report. */
/** Minimal RFC-4180 CSV reader (quoted fields, doubled quotes, CRLF) for a Supabase "export as CSV" of source_uploads. */
export function parseCsv(text) {
  const rows = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); cur = ''; if (row.length > 1 || row[0] !== '') rows.push(row); row = []; }
    else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
  const [head, ...body] = rows;
  return (head ? body : []).map(r => Object.fromEntries(head.map((h, i) => [h.trim(), r[i] === '' || r[i] === undefined ? null : r[i]])));
}

export function loadMetadata(file) {
  if (!file) return [];
  const text = readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const j = /\.csv$/i.test(file) ? parseCsv(text).map(r => ({ ...r, verified_size_bytes: r.verified_size_bytes == null ? null : Number(r.verified_size_bytes), source_size_bytes: r.source_size_bytes == null ? null : Number(r.source_size_bytes) })) : JSON.parse(text);
  const rows = Array.isArray(j) ? j : (j.rows ?? j.entries ?? []);
  return rows.map(r => ({
    key: r.storage_key, status: r.status ?? null, sha256: r.content_sha256 ?? r.sha256 ?? null,
    size: r.verified_size_bytes ?? r.source_size_bytes ?? r.size ?? null, uploadedAt: r.created_at ?? null, batchId: r.batch_id ?? null,
    name: r.source_filename ?? null, uploadId: r.id ?? r.upload_id ?? null,
  })).filter(r => r.key && ['verified', 'superseded', null].includes(r.status));
}

/**
 * Refresh the cloud catalog (read-only against the bucket): list raw/ and processed/ videos, join the durable
 * upload records and the pipeline's processed markers, and upsert one cloud_objects row per source.
 * Records with no object become 'missing' rows (flagged, never invented).
 */
export async function syncCloudCatalog(ctx, { metadata = [] } = {}) {
  if (!ctx.cloud) throw new ApiError('CLOUD_NOT_CONFIGURED');
  const objects = [];
  for (const prefix of SOURCE_PREFIXES) for (const o of await ctx.cloud.list(prefix)) if (isVideo(o.key)) objects.push({ ...o, prefix });
  const markers = new Map();
  for (const m of await ctx.cloud.list(STATE_PREFIX)) {
    try { const j = JSON.parse(await ctx.cloud.getText(m.key, 64 * 1024)); if (j.source_key) markers.set(j.source_key, j); } catch { /* unreadable marker: treated as not processed */ }
  }
  const byKey = new Map(objects.map(o => [o.key, o]));
  const recFor = o => metadata.find(r => r.key === o.key) ?? metadata.find(r => baseName(r.key) === baseName(o.key) && (r.size == null || r.size === o.size));
  const seen = new Set(), t = now();
  const upsert = ctx.db.prepare(`insert into cloud_objects(id,key,prefix,size,etag,last_modified,record_sha256,record_status,record_upload_id,batch_id,uploaded_at,pipeline_state,available,display_name,seen_at)
    values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    on conflict(key) do update set prefix=excluded.prefix,size=excluded.size,etag=excluded.etag,last_modified=excluded.last_modified,
      record_sha256=coalesce(excluded.record_sha256,cloud_objects.record_sha256),record_status=coalesce(excluded.record_status,cloud_objects.record_status),
      record_upload_id=coalesce(excluded.record_upload_id,cloud_objects.record_upload_id),batch_id=coalesce(excluded.batch_id,cloud_objects.batch_id),
      uploaded_at=coalesce(excluded.uploaded_at,cloud_objects.uploaded_at),pipeline_state=excluded.pipeline_state,available=excluded.available,seen_at=excluded.seen_at`);
  tx(ctx.db, () => {
    for (const o of objects) {
      const rec = recFor(o), mk = markers.get(o.key);
      // A marker only counts for the exact bytes that were processed (same size and ETag; quotes are not significant).
      const norm = e => (e ?? '').replace(/"/g, '') || null;
      const state = o.prefix === 'processed/' ? 'processed_legacy' : (mk && mk.size === o.size && norm(mk.etag) === norm(o.etag)) ? 'processed' : 'new';
      upsert.run(randomUUID(), o.key, o.prefix, o.size, o.etag, o.lastModified, rec?.sha256 ?? null, rec?.status ?? null, rec?.uploadId ?? null, rec?.batchId ?? null,
        rec?.uploadedAt ?? o.lastModified ?? null, state, 1, rec?.name ?? baseName(o.key), t);
      seen.add(o.key);
    }
    for (const r of metadata) {
      if (r.status === 'superseded' || seen.has(r.key) || objects.some(o => baseName(o.key) === baseName(r.key) && (r.size == null || o.size === r.size))) continue;
      upsert.run(randomUUID(), r.key, 'raw/', r.size ?? 0, null, null, r.sha256, r.status, r.uploadId, r.batchId, r.uploadedAt, 'unknown', 0, r.name ?? baseName(r.key), t);
      seen.add(r.key);
    }
    // anything we knew about that is no longer listed is flagged unavailable, never deleted from the catalog
    for (const row of ctx.db.prepare('select id,key from cloud_objects where available=1').all()) if (!seen.has(row.key)) ctx.db.prepare('update cloud_objects set available=0 where id=?').run(row.id);
    audit(ctx.db, 'system', 'cloud_catalog_synced', null, { objects: objects.length, markers: markers.size, records: metadata.length });
  });
  return { objects: objects.length, raw: objects.filter(o => o.prefix === 'raw/').length, processed_legacy: objects.filter(o => o.prefix === 'processed/').length,
    missing: ctx.db.prepare('select count(*) n from cloud_objects where available=0').get().n };
}

export function listCloudObjects(db) {
  return db.prepare(`select c.id, c.key, c.prefix, c.size, c.uploaded_at, c.display_name, c.pipeline_state, c.available, c.record_sha256, c.record_status, c.batch_id, c.source_id,
      s.primary_sport_id, s.duration_ms, s.verify_state, s.proxy_path, s.thumb_path, s.frame_count
    from cloud_objects c left join sources s on s.id=c.source_id order by c.uploaded_at desc, c.key`).all().map(r => ({
    id: r.id, key: r.key, name: r.display_name, size: r.size, uploaded_at: r.uploaded_at, batch_id: r.batch_id, location: r.prefix,
    availability: r.available ? (r.prefix === 'processed/' ? 'legacy_processed' : 'available') : 'missing',
    pipeline_state: r.pipeline_state, sport_id: r.primary_sport_id ?? null, duration_ms: r.duration_ms ?? null,
    source_id: r.source_id, opened: !!r.source_id, verify_state: r.verify_state ?? null, identity: r.record_sha256 ? 'recorded' : 'unknown',
    annotation_status: null, has_thumb: !!r.thumb_path,
  }));
}

/**
 * Open a cloud object for annotation: establish identity (sha256 from the durable record, or by streaming the bytes),
 * probe it over the authenticated local media route, register it as a source and prepare thumbnail/proxy.
 * Never copies or modifies the cloud object.
 */
const opening = new Map();
export function openCloudObject(ctx, id, opts) {
  // Opening twice at once (double click) must not register the same bytes twice: share the in-flight work.
  if (!opening.has(id)) opening.set(id, openCloudObjectOnce(ctx, id, opts).finally(() => opening.delete(id)));
  return opening.get(id);
}

async function openCloudObjectOnce(ctx, id, { baseUrl }) {
  const obj = ctx.db.prepare('select * from cloud_objects where id=?').get(id);
  if (!obj) throw new ApiError('NOT_FOUND');
  if (obj.source_id) return { source_id: obj.source_id, reused: true };
  if (!obj.available) throw new ApiError('SOURCE_UNAVAILABLE');
  const head = await ctx.cloud.head(obj.key);
  if (!head) throw new ApiError('SOURCE_UNAVAILABLE');
  if (obj.record_sha256 && obj.size && head.size !== obj.size) throw new ApiError('INVALID_INPUT', 'גודל האובייקט בענן שונה מהרשומה הקבועה');
  let sha = obj.record_sha256, verified = false;
  if (!sha) { sha = await ctx.cloud.sha256(obj.key); verified = true; }           // identity from the actual bytes
  const existing = ctx.db.prepare('select * from sources where sha256=? and byte_size=?').get(sha, head.size);
  if (existing) {                                                                  // the same bytes are already a source: link, do not duplicate
    tx(ctx.db, () => {
      ctx.db.prepare('update cloud_objects set source_id=? where id=?').run(existing.id, id);
      const have = ctx.db.prepare("select 1 from source_locations where source_id=? and key=? and provider='cloud-r2'").get(existing.id, obj.key);
      if (!have) ctx.db.prepare("insert into source_locations(source_id,provider,bucket,key,kind,observed_at,active) values(?,?,?,?,'operational',?,1)").run(existing.id, 'cloud-r2', ctx.cloud.bucket, obj.key, now());
    });
    return { source_id: existing.id, reused: true };
  }
  const url = `${baseUrl}/media/cloud/${id}/original`;
  const meta = await probe(url, { headers: `Authorization: Bearer ${ctx.token}\r\n` });
  const sid = randomUUID();
  tx(ctx.db, () => {
    ctx.db.prepare(`insert into sources(id,sha256,byte_size,display_name,session_key,codec,width,height,rotation,fps_num,fps_den,frame_count,duration_ms,captured_at,ingest_state,provider,cloud_key,verify_state,archive_verified_at,created_at)
      values(?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'ready','cloud-r2',?,?,?,?)`)
      .run(sid, sha, head.size, obj.display_name ?? baseName(obj.key), meta.captured_at ? meta.captured_at.slice(0, 10) : (obj.batch_id ?? null), meta.codec, meta.width, meta.height, meta.rotation,
        meta.fps_num, meta.fps_den, meta.frame_count, meta.duration_ms, meta.captured_at, obj.key, verified ? 'verified' : 'unverified', verified ? now() : null, now());
    ctx.db.prepare('update cloud_objects set source_id=? where id=?').run(sid, id);
    ctx.db.prepare("insert into source_locations(source_id,provider,bucket,key,kind,observed_at,active,verified_sha256) values(?,?,?,?,'operational',?,1,?)").run(sid, 'cloud-r2', ctx.cloud.bucket, obj.key, now(), verified ? sha : null);
    audit(ctx.db, 'operator', 'cloud_source_opened', sid, { key: obj.key, identity: verified ? 'hashed_from_bytes' : 'from_durable_record' });
  });
  const dir = path.join(ctx.cacheDir, sid), headers = `Authorization: Bearer ${ctx.token}\r\n`;
  try { const t = path.join(dir, 'thumb.jpg'); await makeThumb(url, t, { headers }); ctx.db.prepare('update sources set thumb_path=? where id=?').run(t, sid); }
  catch (e) { audit(ctx.db, 'system', 'thumb_failed', sid, { error: e.message }); }
  return { source_id: sid, reused: false, proxy: buildProxyInBackground(ctx, sid, url, meta) };
}

const proxyJobs = new Map();
/** Frame-accurate annotation proxy, built from the cloud object by ranged reads; stored locally, never in the bucket. */
export function buildProxyInBackground(ctx, sid, url, meta) {
  if (proxyJobs.has(sid)) return proxyJobs.get(sid);
  const p = path.join(ctx.cacheDir, sid, 'proxy.webm');
  ctx.db.prepare("update sources set proxy_state='building' where id=?").run(sid);
  const job = makeProxy(url, p, { fpsNum: meta.fps_num, fpsDen: meta.fps_den, headers: `Authorization: Bearer ${ctx.token}\r\n` })
    .then(() => { ctx.db.prepare("update sources set proxy_path=?, proxy_state='ready' where id=?").run(p, sid); })
    .catch(e => { ctx.db.prepare("update sources set proxy_state='failed' where id=?").run(sid); audit(ctx.db, 'system', 'proxy_failed', sid, { error: e.message }); })
    .finally(() => proxyJobs.delete(sid));
  proxyJobs.set(sid, job);
  return job;
}
export const waitForProxies = () => Promise.allSettled([...proxyJobs.values()]);

/** Re-hash every unverified cloud source from the bucket bytes; Ground Truth approval requires verify_state='verified'. */
export async function verifyCloudSources(ctx, { onlyId } = {}) {
  const rows = ctx.db.prepare(`select id,sha256,byte_size,cloud_key from sources where provider='cloud-r2' and verify_state!='verified' ${onlyId ? 'and id=?' : ''}`).all(...(onlyId ? [onlyId] : []));
  const out = { checked: 0, verified: 0, mismatched: [] };
  for (const s of rows) {
    out.checked++;
    const h = await ctx.cloud.head(s.cloud_key);
    const actual = h && h.size === s.byte_size ? await ctx.cloud.sha256(s.cloud_key) : null;
    if (actual === s.sha256) {
      ctx.db.prepare("update sources set verify_state='verified', archive_verified_at=? where id=?").run(now(), s.id); out.verified++;
      audit(ctx.db, 'system', 'cloud_source_verified', s.id, { key: s.cloud_key });
    } else {
      ctx.db.prepare("update sources set verify_state='mismatch' where id=?").run(s.id); out.mismatched.push(s.id);
      audit(ctx.db, 'system', 'cloud_source_mismatch', s.id, { key: s.cloud_key, reason: h ? 'hash_or_size' : 'missing' });
    }
  }
  return out;
}
