// HTTP layer: localhost-only, token-authenticated JSON API + range-capable media streaming.
import http from 'node:http';
import { createReadStream, existsSync, statSync, readFileSync } from 'node:fs';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ApiError } from './errors.mjs';
import { now, audit } from './db.mjs';
import * as A from './annotations.mjs';
import * as D from './datasets.mjs';
import * as E from './evaluate.mjs';
import * as L from './edl.mjs';
import { reconcile, verifyArchives } from './ingest.mjs';

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml', '.json': 'application/json', '.jpg': 'image/jpeg', '.webm': 'video/webm', '.mp4': 'video/mp4', '.mov': 'video/quicktime' };

const safeEq = (a, b) => { const x = Buffer.from(a), y = Buffer.from(b); return x.length === y.length && timingSafeEqual(x, y); };

export function createApp(ctx) {
  const { db, token } = ctx;
  const jobs = new Map();

  function authed(req) {
    const h = req.headers.authorization;
    if (h?.startsWith('Bearer ') && safeEq(h.slice(7), token)) return true;
    const m = /(?:^|;\s*)studio_token=([^;]+)/.exec(req.headers.cookie ?? '');
    return !!m && safeEq(decodeURIComponent(m[1]), token);
  }
  const hostOk = req => /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(req.headers.host ?? '');

  async function body(req) {
    let n = 0; const chunks = [];
    for await (const c of req) { n += c.length; if (n > 8e6) throw new ApiError('INVALID_INPUT', 'גוף בקשה גדול מדי'); chunks.push(c); }
    if (!n) return {};
    try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new ApiError('INVALID_INPUT'); }
  }
  const send = (res, status, obj, extra = {}) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...extra });
    res.end(JSON.stringify(obj));
  };

  function sourceCard(s) {
    const content = A.getDraft(db, s.id).content;
    const cov = A.reviewedCoverage(content, s.frame_count || 0);
    const rev = A.latestRevision(db, s.id);
    const occ = db.prepare('select b.label, o.original_name from upload_occurrences o join upload_batches b on b.id=o.batch_id where o.source_id=? order by o.id').all(s.id);
    return {
      id: s.id, display_name: s.display_name, sha256: s.sha256, byte_size: s.byte_size, width: s.width, height: s.height,
      fps_num: s.fps_num, fps_den: s.fps_den, frame_count: s.frame_count, duration_ms: s.duration_ms, rotation: s.rotation,
      ingest_state: s.ingest_state, archive_verified_at: s.archive_verified_at, archive_error: s.archive_error,
      annotation_status: A.annotationStatus(db, s.id), revision_seq: rev?.seq ?? 0, reviewed_ratio: cov.ratio,
      segment_count: content.segments.length, batches: [...new Set(occ.map(o => o.label))],
      has_thumb: !!s.thumb_path, has_proxy: !!s.proxy_path, created_at: s.created_at,
    };
  }

  async function api(req, res, url) {
    const p = url.pathname, m = req.method;
    let r;
    if (m === 'GET' && p === '/api/health') return send(res, 200, { ok: true, schema: 1 });
    if (m === 'GET' && p === '/api/sources') {
      const status = url.searchParams.get('status'), qs = (url.searchParams.get('q') ?? '').toLowerCase(), batch = url.searchParams.get('batch');
      const limit = Math.min(200, Number(url.searchParams.get('limit') ?? 50)), cursor = url.searchParams.get('cursor') ?? '';
      let rows = db.prepare('select * from sources where created_at||id > ? order by created_at,id').all(cursor);
      let items = rows.map(sourceCard);
      if (qs) items = items.filter(s => s.display_name.toLowerCase().includes(qs) || s.sha256.startsWith(qs));
      if (batch) items = items.filter(s => s.batches.includes(batch));
      if (status) items = items.filter(s => s.annotation_status === status || s.ingest_state === status);
      const page = items.slice(0, limit);
      const last = page.at(-1);
      return send(res, 200, { items: page, next_cursor: items.length > limit && last ? last.created_at + last.id : null,
        totals: { all: rows.length, approved: rows.filter(s => A.annotationStatus(db, s.id) === 'approved').length,
          not_annotated: rows.filter(s => A.annotationStatus(db, s.id) === 'not_annotated').length } });
    }
    if ((r = /^\/api\/sources\/([\w-]+)$/.exec(p)) && m === 'GET') {
      const s = db.prepare('select * from sources where id=?').get(r[1]); if (!s) throw new ApiError('NOT_FOUND');
      if (s.ingest_state !== 'ready') throw new ApiError('ARCHIVE_UNVERIFIED');
      const locations = db.prepare('select provider,kind,key,active,observed_at from source_locations where source_id=?').all(s.id);
      return send(res, 200, { ...sourceCard(s), locations, playback_url: s.proxy_path ? `/media/${s.id}/proxy` : `/media/${s.id}/original`, thumb_url: s.thumb_path ? `/media/${s.id}/thumb` : null });
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/draft$/.exec(p))) {
      if (m === 'GET') return send(res, 200, A.getDraft(db, r[1]));
      if (m === 'PUT') { const b = await body(req); return send(res, 200, A.saveDraft(db, r[1], b.expected_version, b.content)); }
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/approve$/.exec(p)) && m === 'POST') {
      const b = await body(req);
      const out = A.approve(db, r[1], { expectedVersion: b.expected_version, scope: b.scope, reason: b.reason, acknowledgeUnresolved: !!b.acknowledge_unresolved });
      return send(res, 200, { revision: { id: out.revision.id, seq: out.revision.seq, digest: out.revision.digest, approved_at: out.revision.approved_at }, unchanged: out.unchanged, unresolved: out.unresolved });
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/revisions$/.exec(p)) && m === 'GET') return send(res, 200, { items: A.listRevisions(db, r[1]) });
    if ((r = /^\/api\/revisions\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, 200, A.getRevision(db, r[1]));
    if (m === 'GET' && p === '/api/batches') return send(res, 200, { items: db.prepare(`select b.id,b.label,b.created_at,count(distinct o.source_id) sources from upload_batches b left join upload_occurrences o on o.batch_id=b.id group by b.id order by b.created_at desc`).all() });
    if (m === 'POST' && p === '/api/ingestion/reconcile') {
      const b = await body(req);
      const id = randomUUID(); jobs.set(id, { state: 'running' });
      reconcile(ctx, { roots: ctx.roots, deep: !!b.deep }).then(rep => jobs.set(id, { state: 'done', report: rep }), e => jobs.set(id, { state: 'failed', error: e.message }));
      return send(res, 202, { job_id: id });
    }
    if ((r = /^\/api\/jobs\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, jobs.has(r[1]) ? 200 : 404, jobs.get(r[1]) ?? { code: 'NOT_FOUND' });
    if (m === 'POST' && p === '/api/archive/verify') return send(res, 200, await verifyArchives(ctx));
    if (p === '/api/athletes') {
      if (m === 'GET') return send(res, 200, { items: A.listAthletes(db) });
      if (m === 'POST') { const b = await body(req); return send(res, 201, A.createAthlete(db, b.label, b.notes)); }
    }
    if ((r = /^\/api\/athletes\/([\w-]+)$/.exec(p)) && m === 'PATCH') { const b = await body(req); A.renameAthlete(db, r[1], b.label, b.notes); return send(res, 200, { ok: true }); }
    if ((r = /^\/api\/athletes\/([\w-]+)\/appearances\/([\w-]+)$/.exec(p)) && m === 'PATCH') { A.setAppearanceFlags(db, r[1], r[2], await body(req)); return send(res, 200, { ok: true }); }
    if (p === '/api/datasets') {
      if (m === 'GET') return send(res, 200, { items: D.listDatasets(db) });
      if (m === 'POST') { const b = await body(req); const o = D.freezeDataset(db, { name: b.name, sourceIds: b.source_ids, policy: b.policy }); return send(res, 201, { id: o.id, digest: o.digest, manifest: o.manifest }); }
    }
    if ((r = /^\/api\/datasets\/([\w-]+)$/.exec(p)) && m === 'GET') { const d = db.prepare('select id,name,digest,manifest,created_at from dataset_versions where id=?').get(r[1]); if (!d) throw new ApiError('NOT_FOUND'); return send(res, 200, { ...d, manifest: JSON.parse(d.manifest) }); }
    if ((r = /^\/api\/datasets\/([\w-]+)\/export\.jsonl$/.exec(p)) && m === 'GET') {
      res.writeHead(200, { 'content-type': 'application/x-ndjson', 'cache-control': 'no-store' }); return res.end(D.exportJsonl(db, r[1]));
    }
    if ((r = /^\/api\/datasets\/([\w-]+)\/blind-manifest$/.exec(p)) && m === 'GET') return send(res, 200, { items: D.blindInferenceManifest(db, r[1]) });
    if (p === '/api/predictions') {
      if (m === 'POST') return send(res, 201, E.importPredictions(db, await body(req)));
      if (m === 'GET') return send(res, 200, { items: db.prepare('select id,run_id,pipeline_version,digest,created_at from pipeline_predictions order by created_at desc').all() });
    }
    if (p === '/api/evaluations') {
      if (m === 'POST') { const o = E.runEvaluation(db, await body(req)); return send(res, 201, { id: o.id, digest: o.digest }); }
      if (m === 'GET') return send(res, 200, { items: E.listEvaluations(db) });
    }
    if ((r = /^\/api\/evaluations\/([\w-]+)$/.exec(p)) && m === 'GET') { const e = db.prepare('select report,digest from evaluation_runs where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND'); return send(res, 200, { digest: e.digest, report: JSON.parse(e.report) }); }
    if (m === 'GET' && p === '/api/outputs') return send(res, 200, { items: db.prepare('select id,output_id,run_id,source_id,created_at,payload from edl_records order by created_at desc').all().map(e => { const x = JSON.parse(e.payload); return { id: e.id, output_id: e.output_id, run_id: e.run_id, source_id: e.source_id, mode: x.mode, has_video: !!x.output_file, mapping: x.mapping ?? 'verified', output: x.output, source: x.source }; }) });
    if ((r = /^\/api\/outputs\/([\w-]+)\/edl$/.exec(p)) && m === 'GET') { const e = db.prepare('select payload from edl_records where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND'); return send(res, 200, JSON.parse(e.payload)); }
    if ((r = /^\/api\/outputs\/([\w-]+)\/review$/.exec(p)) && m === 'GET') {
      const e = db.prepare('select payload,source_id from edl_records where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND');
      const edl = JSON.parse(e.payload), rev = e.source_id && A.latestRevision(db, e.source_id);
      if (!rev) return send(res, 200, { edl, verified: false, report: L.evaluateEditing(null, A.emptyContent()), frames: [], revision: null });
      const gt = JSON.parse(rev.content);
      return send(res, 200, { edl, revision: { id: rev.id, seq: rev.seq }, report: L.evaluateEditing(edl, gt), ...L.frameEvidence(edl, gt), source_id: e.source_id });
    }
    if (m === 'POST' && p === '/api/editing/evaluate') {
      const b = await body(req);
      const rec = b.edl_id ? db.prepare('select payload,source_id from edl_records where id=?').get(b.edl_id) : null;
      const rev = A.getRevision(db, b.revision_id);
      const rep = L.evaluateEditing(rec ? JSON.parse(rec.payload) : null, rev.content, { thresholds: b.thresholds });
      const id = randomUUID();
      db.prepare('insert into editing_reports(id,edl_id,revision_id,evaluator_version,report,digest,created_at) values(?,?,?,?,?,?,?)').run(id, b.edl_id ?? null, b.revision_id, rep.evaluator_version, JSON.stringify(rep), A.digestOf(rep), now());
      return send(res, 200, { id, report: rep });
    }
    if (m === 'POST' && p === '/api/editing/proposals') {
      const b = await body(req);
      const s = db.prepare('select * from sources where id=?').get(b.source_id); if (!s) throw new ApiError('NOT_FOUND');
      A.validateBbox(b.bbox);
      const prop = L.proposeCrop({ source: s, bbox: b.bbox, mode: b.mode, target: b.target });
      const id = randomUUID();
      db.prepare('insert into crop_proposals(id,source_id,status,payload,created_at) values(?,?,?,?,?)').run(id, s.id, 'proposal', JSON.stringify(prop), now());
      return send(res, 201, { id, proposal: prop });
    }
    if ((r = /^\/api\/editing\/proposals\/([\w-]+)\/approve$/.exec(p)) && m === 'POST') {
      const prop = db.prepare('select * from crop_proposals where id=?').get(r[1]); if (!prop) throw new ApiError('NOT_FOUND');
      const id = randomUUID();
      db.prepare('insert into crop_proposals(id,source_id,status,payload,created_at) values(?,?,?,?,?)').run(id, prop.source_id, 'approved', JSON.stringify({ ...JSON.parse(prop.payload), status: 'approved', from_proposal: prop.id }), now());
      audit(db, 'operator', 'crop_approved', id, { from: prop.id });
      return send(res, 201, { id });
    }
    if (m === 'GET' && p === '/api/audit') return send(res, 200, { items: db.prepare('select * from audit_log order by id desc limit 200').all() });
    throw new ApiError('NOT_FOUND');
  }

  async function media(req, res, id, kind) {
    let file = null, archiveKey = null;
    if (kind === 'out') {
      const e = db.prepare('select payload from edl_records where id=?').get(id);
      const f = e && JSON.parse(e.payload).output_file;
      file = f && path.join(ctx.outputsDir, path.basename(f));
    } else {
      const s = db.prepare('select * from sources where id=?').get(id);
      if (!s) return send(res, 404, { code: 'NOT_FOUND' });
      if (kind === 'original') archiveKey = s.archive_key; else file = kind === 'thumb' ? s.thumb_path : s.proxy_path;
    }
    const type = kind === 'thumb' ? 'image/jpeg' : kind === 'original' ? 'video/mp4' : (MIME[path.extname(file ?? '')] ?? 'application/octet-stream');
    let size, open;
    if (archiveKey) {
      size = await ctx.archive.size(archiveKey);
      open = o => ctx.archive.open(archiveKey, o);
    } else if (file && existsSync(file)) { size = statSync(file).size; open = async o => createReadStream(file, o); }
    if (size == null) return send(res, 404, { code: 'SOURCE_UNAVAILABLE' });
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? '');
    if (range) {
      let a = range[1] === '' ? size - Number(range[2]) : Number(range[1]);
      let b = range[1] !== '' && range[2] !== '' ? Number(range[2]) : size - 1;
      if (!(a >= 0 && b < size && a <= b)) { res.writeHead(416, { 'content-range': `bytes */${size}` }); return res.end(); }
      res.writeHead(206, { 'content-type': type, 'content-range': `bytes ${a}-${b}/${size}`, 'accept-ranges': 'bytes', 'content-length': b - a + 1, 'cache-control': 'private, max-age=60' });
      return (await open({ start: a, end: b })).pipe(res);
    }
    res.writeHead(200, { 'content-type': type, 'accept-ranges': 'bytes', 'content-length': size, 'cache-control': 'private, max-age=60' });
    (await open()).pipe(res);
  }

  function serveStatic(res, pathname) {
    const rel = pathname === '/' ? 'index.html' : pathname.slice(1);
    const file = path.join(WEB, rel);
    if (!file.startsWith(WEB + path.sep) || !existsSync(file) || !statSync(file).isFile()) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store',
      'content-security-policy': "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'" });
    res.end(readFileSync(file));
  }

  return http.createServer(async (req, res) => {
    try {
      if (!hostOk(req)) return send(res, 403, { code: 'PERMISSION_DENIED' });
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/' && url.searchParams.get('t') && safeEq(url.searchParams.get('t'), token)) {
        res.writeHead(302, { location: '/', 'set-cookie': `studio_token=${encodeURIComponent(token)}; HttpOnly; SameSite=Strict; Path=/` });
        return res.end();
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) {
        if (!authed(req)) return send(res, 401, { code: 'PERMISSION_DENIED', message: new ApiError('PERMISSION_DENIED').he });
        if (req.method !== 'GET') {
          const o = req.headers.origin;
          if (o && !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(o)) return send(res, 403, { code: 'PERMISSION_DENIED' });
        }
        const mm = /^\/media\/([\w-]+)\/(proxy|thumb|original|out)$/.exec(url.pathname);
        if (mm) return await media(req, res, mm[1], mm[2]);
        return await api(req, res, url);
      }
      return serveStatic(res, url.pathname);
    } catch (e) {
      if (e instanceof ApiError) return send(res, e.status, { code: e.code, message: e.he, detail: e.message, unresolved: e.unresolved });
      if (/IMMUTABLE|PROTECTED/.test(e?.message ?? '')) return send(res, 409, { code: 'IMMUTABLE', message: 'רשומה בלתי ניתנת לשינוי' });
      console.error('[studio] internal error:', e?.message);
      return send(res, 500, { code: 'INTERNAL', message: 'שגיאה פנימית' });
    }
  });
}
