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
import * as Rv from './review.mjs';
import * as L from './edl.mjs';
import * as S from './sports.mjs';
import * as C from './cloud.mjs';
import * as Catalog from './catalog_owner.mjs';
import { reconcile, verifyArchives } from './ingest.mjs';
import * as I from './imports.mjs';
import { exportBackup, verifyIntegrity, restoreBackup, BACKUP_FORMAT } from './backup.mjs';
import { backupStatus } from './offsite.mjs';
import * as Sets from './sets.mjs';
import * as Lin from './lineage.mjs';
import * as QC from './quickcatalog.mjs';
import { spawnSync } from 'node:child_process';
import { gunzipSync } from 'node:zlib';
import { dbTlsMode } from './db.mjs';

/** The running code's git commit (or package version), shown in the UI so the operator can tell which version is open. */
let versionCache = null;
function appVersion() {
  if (versionCache) return versionCache;
  const here = path.dirname(fileURLToPath(import.meta.url));
  let commit = process.env.VERCEL_GIT_COMMIT_SHA ? process.env.VERCEL_GIT_COMMIT_SHA.slice(0, 7) : null;   // hosted builds have no .git
  if (!commit) try { const r = spawnSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: here, encoding: 'utf8', timeout: 3000 }); if (r.status === 0) commit = r.stdout.trim() || null; } catch { /* git not installed */ }
  let version = null;
  try { version = JSON.parse(readFileSync(path.join(here, '..', 'package.json'), 'utf8')).version ?? null; } catch { /* no package.json */ }
  return (versionCache = { commit, version });
}

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
  const isLocalHost = req => /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(req.headers.host ?? '');
  // localhost, or a host name this deployment was explicitly given (studio.<domain>, its *.vercel.app names); anything else
  // (DNS rebinding, stray domains pointed at the deployment) is refused.
  const hostOk = req => isLocalHost(req) || (ctx.allowedHosts ?? []).includes((req.headers.host ?? '').toLowerCase());
  const originOk = o => /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(o) || (ctx.allowedHosts ?? []).some(h => o.toLowerCase() === `https://${h}`);
  // The login cookie is HttpOnly + SameSite=Strict, persistent (1 year), and Secure whenever the request came over HTTPS.
  const loginCookie = req => `studio_token=${encodeURIComponent(token)}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000${req.headers['x-forwarded-proto'] === 'https' ? '; Secure' : ''}`;

  async function body(req) {
    let n = 0; const chunks = [];
    for await (const c of req) { n += c.length; if (n > 8e6) throw new ApiError('INVALID_INPUT', 'גוף בקשה גדול מדי'); chunks.push(c); }
    if (!n) return {};
    let raw = Buffer.concat(chunks);
    // gzip bodies (the one-time import of a local Studio) keep large exports under hosted request-size limits.
    if (/\bgzip\b/i.test(req.headers['content-encoding'] ?? '')) {
      try { raw = gunzipSync(raw, { maxOutputLength: 128e6 }); } catch { throw new ApiError('INVALID_INPUT', 'גוף בקשה דחוס לא תקין'); }
    }
    try { return JSON.parse(raw.toString('utf8')); } catch { throw new ApiError('INVALID_INPUT'); }
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
    const ownerAthlete = s.owner_athlete_id ? db.prepare('select id, label from athletes where id=?').get(s.owner_athlete_id) : null;
    return {
      id: s.id, display_name: s.display_name, sha256: s.sha256, byte_size: s.byte_size, width: s.width, height: s.height,
      fps_num: s.fps_num, fps_den: s.fps_den, frame_count: s.frame_count, duration_ms: s.duration_ms, rotation: s.rotation,
      codec: s.codec ?? null, primary_sport_id: s.primary_sport_id ?? null, suggested_sport_id: s.suggested_sport_id ?? null, sport_suggestion_source: s.sport_suggestion_source ?? null, provider: s.provider ?? 'local', verify_state: s.verify_state ?? null, proxy_state: s.proxy_state ?? (s.proxy_path ? 'ready' : null),
      session_key: s.session_key ?? null,
      owner_athlete_id: s.owner_athlete_id ?? null,
      owner_status: s.owner_status ?? 'unassigned',
      owner_athlete_label: ownerAthlete?.label ?? null,
      owner_assigned_at: s.owner_assigned_at ?? null,
      owner_assigned_by: s.owner_assigned_by ?? null,
      owner_version: Number(s.owner_version ?? 0),
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
      const sport = url.searchParams.get('sport');
      const owner = url.searchParams.get('owner');
      const limit = Math.min(200, Number(url.searchParams.get('limit') ?? 50)), cursor = url.searchParams.get('cursor') ?? '';
      let rows = db.prepare('select * from sources where created_at||id > ? order by created_at,id').all(cursor);
      let items = rows.map(sourceCard);
      if (qs) items = items.filter(s => s.display_name.toLowerCase().includes(qs) || s.sha256.startsWith(qs));
      if (batch) items = items.filter(s => s.batches.includes(batch));
      if (sport) items = items.filter(s => (s.primary_sport_id ?? 'unknown') === sport);
      if (owner) items = items.filter(s => s.owner_athlete_id === owner);
      if (status) items = items.filter(s => s.annotation_status === status || s.ingest_state === status || s.owner_status === status);
      const page = items.slice(0, limit);
      const last = page.at(-1);
      return send(res, 200, { items: page, next_cursor: items.length > limit && last ? last.created_at + last.id : null,
        totals: { all: rows.length, approved: rows.filter(s => A.annotationStatus(db, s.id) === 'approved').length,
          not_annotated: rows.filter(s => A.annotationStatus(db, s.id) === 'not_annotated').length,
          assigned: rows.filter(s => s.owner_athlete_id != null).length,
          unassigned: rows.filter(s => s.owner_athlete_id == null).length,
          by_sport: rows.reduce((o, s) => { const k = s.primary_sport_id ?? 'unknown'; o[k] = (o[k] ?? 0) + 1; return o; }, {}) } });
    }

    // ---- Quick catalog: one queue with every catalog field per video and per event (reads/writes the same stores) ----
    if (m === 'GET' && p === '/api/version') return send(res, 200, { ...appVersion(), hosted: !!ctx.serverless, backend: ctx.dbUrl ? 'postgresql' : 'sqlite', db_tls: ctx.dbUrl ? dbTlsMode() : null });
    if (m === 'GET' && p === '/api/catalog/queue') return send(res, 200, QC.catalogQueue(db, { include: ctx.cloudInclude ?? '', likeContains: C.likeContains }));
    if ((r = /^\/api\/catalog\/sources\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, 200, QC.sourceCatalogState(db, A.getSource(db, r[1])));
    if ((r = /^\/api\/catalog\/sources\/([\w-]+)\/triage$/.exec(p)) && m === 'POST') { const b = await body(req); return send(res, 200, QC.setTriage(db, r[1], b)); }

    // ---- Catalog Ownership (Precision Studio V2) ----
    if ((r = /^\/api\/sources\/([\w-]+)\/catalog-owner$/.exec(p))) {
      if (m === 'GET') return send(res, 200, Catalog.getCatalogOwner(db, r[1]));
      if (m === 'POST' || m === 'PUT') { const b = await body(req); return send(res, 200, Catalog.setCatalogOwner(db, r[1], b)); }
    }
    if (p === '/api/sources/catalog-owners/bulk' && m === 'POST') {
      const b = await body(req); return send(res, 200, Catalog.bulkSetCatalogOwner(db, b));
    }
    if ((r = /^\/api\/athletes\/([\w-]+)\/sources$/.exec(p)) && m === 'GET') {
      return send(res, 200, Catalog.listAthleteSources(db, r[1], { filter: url.searchParams.get('filter') ?? 'all' }));
    }
    if ((r = /^\/api\/cloud\/objects\/([\w-]+)\/catalog-owner$/.exec(p)) && m === 'POST') {
      const b = await body(req); return send(res, 200, Catalog.setCloudObjectCatalogOwner(db, r[1], b));
    }

    // ---- Cloud catalog (existing SportReel videos in R2, used in place; the bucket is only ever read) ----
    if (m === 'GET' && p === '/api/cloud/status') {
      const inc = ctx.cloudInclude ?? '', like = C.likeContains(inc);
      const n = db.prepare("select count(*) total, sum(case when available=1 then 1 else 0 end) available, sum(case when source_id is not null then 1 else 0 end) opened from cloud_objects where (? = '' or key like ? escape '\\' or display_name like ? escape '\\')").get(inc, like, like);
      return send(res, 200, { configured: !!ctx.cloud, bucket: ctx.cloud?.bucket ?? null, read_only: true, metadata_file: !!ctx.cloudMetadata, include_filter: ctx.cloudInclude || null,
        total: Number(n.total ?? 0), available: Number(n.available ?? 0), opened: Number(n.opened ?? 0) });
    }
    if (m === 'GET' && p === '/api/cloud/objects') {
      if (!ctx.cloud) throw new ApiError('CLOUD_NOT_CONFIGURED');
      return send(res, 200, {
        items: C.listCloudObjects(db, ctx.cloudInclude).map(o => {
          const ownerAthlete = o.owner_athlete_id ? db.prepare('select id, label from athletes where id=?').get(o.owner_athlete_id) : null;
          return {
            ...o,
            owner_athlete_id: o.owner_athlete_id ?? null,
            owner_status: o.owner_status ?? 'unassigned',
            owner_version: Number(o.owner_version ?? 0),
            owner_athlete_label: ownerAthlete?.label ?? null,
            annotation_status: o.source_id ? A.annotationStatus(db, o.source_id) : 'not_annotated',
          };
        }),
      });
    }
    if (m === 'POST' && p === '/api/cloud/sync') {
      if (!ctx.cloud) throw new ApiError('CLOUD_NOT_CONFIGURED');
      return startJob(res, () => C.syncCloudCatalog(ctx, { metadata: C.loadMetadata(ctx.cloudMetadata) }));
    }
    if ((r = /^\/api\/cloud\/objects\/([\w-]+)\/open$/.exec(p)) && m === 'POST') {
      if (!ctx.cloud) throw new ApiError('CLOUD_NOT_CONFIGURED');
      return startJob(res, async () => { const rep = await C.openCloudObject(ctx, r[1], { baseUrl: `http://${req.headers.host}` }); return { source_id: rep.source_id, reused: rep.reused }; });
    }
    if (m === 'POST' && p === '/api/cloud/verify') {
      if (!ctx.cloud) throw new ApiError('CLOUD_NOT_CONFIGURED');
      const b = await body(req);
      return startJob(res, () => C.verifyCloudSources(ctx, { onlyId: b.source_id }));
    }
    if (m === 'POST' && p === '/api/sources/bulk-sport') { const b = await body(req); return send(res, 200, S.bulkSetSport(db, b.source_ids, b.sport_id ?? null, b.reason)); }
    if ((r = /^\/api\/sources\/([\w-]+)\/sport$/.exec(p)) && m === 'PATCH') {
      const b = await body(req);
      return send(res, 200, S.setSourceSport(db, r[1], b.sport_id ?? null, { reason: b.reason, acknowledgeIncompatible: !!b.acknowledge_incompatible, remap: b.remap }));
    }
    if (p === '/api/sports') {
      if (m === 'GET') return send(res, 200, { items: S.listSports(db) });
      if (m === 'POST') return send(res, 201, S.addSport(db, await body(req)));
    }
    if ((r = /^\/api\/sports\/([\w-]+)$/.exec(p)) && m === 'PATCH') { S.setSportEnabled(db, r[1], !!(await body(req)).enabled); return send(res, 200, { ok: true }); }
    if ((r = /^\/api\/sports\/([\w-]+)\/event-types$/.exec(p)) && m === 'POST') return send(res, 201, S.addEventType(db, r[1], await body(req)));
    if ((r = /^\/api\/sports\/([\w-]+)\/event-types\/([\w-]+)$/.exec(p)) && m === 'PATCH') return send(res, 200, S.setEventTypeEnabled(db, r[1], r[2], !!(await body(req)).enabled));
    if ((r = /^\/api\/sources\/([\w-]+)$/.exec(p)) && m === 'GET') {
      const s = db.prepare('select * from sources where id=?').get(r[1]); if (!s) throw new ApiError('NOT_FOUND');
      if (s.ingest_state !== 'ready') throw new ApiError('ARCHIVE_UNVERIFIED');
      const locations = db.prepare('select provider,kind,key,active,observed_at from source_locations where source_id=?').all(s.id);
      return send(res, 200, { ...sourceCard(s), locations, playback_url: (s.proxy_path && !ctx.serverless) || (ctx.serverless && ctx.previews && s.provider === 'cloud-r2') ? `/media/${s.id}/proxy` : `/media/${s.id}/original`, thumb_url: s.thumb_path && !ctx.serverless ? `/media/${s.id}/thumb` : null });
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/draft$/.exec(p))) {
      if (m === 'GET') return send(res, 200, A.getDraft(db, r[1]));
      if (m === 'PUT') { const b = await body(req); return send(res, 200, A.saveDraft(db, r[1], b.expected_version, b.content)); }
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/draft\/reset$/.exec(p)) && m === 'POST') { const b = await body(req); return send(res, 200, A.resetDraft(db, r[1], b.expected_version)); }
    if ((r = /^\/api\/sources\/([\w-]+)\/draft\/restore$/.exec(p)) && m === 'POST') { const b = await body(req); return send(res, 200, A.restoreReset(db, r[1], b.expected_version)); }
    if ((r = /^\/api\/sources\/([\w-]+)\/approve$/.exec(p)) && m === 'POST') {
      const b = await body(req);
      const out = A.approve(db, r[1], { expectedVersion: b.expected_version, scope: b.scope, reason: b.reason, acknowledgeUnresolved: !!b.acknowledge_unresolved, acceptByException: !!b.accept_by_exception });
      return send(res, 200, { revision: { id: out.revision.id, seq: out.revision.seq, digest: out.revision.digest, approved_at: out.revision.approved_at }, unchanged: out.unchanged, unresolved: out.unresolved, approval_caveats: out.approval_caveats, accepted_by_exception: out.accepted_by_exception ?? 0, draft_version: out.draft_version });
    }
    // ---- Independent annotation sets, agreement, adjudication (addendum §2, §8, §9) ----
    if (p === '/api/sets') {
      if (m === 'GET') return send(res, 200, { items: Sets.listSets(db) });
      if (m === 'POST') return send(res, 201, Sets.createSet(db, await body(req)));
    }
    if ((r = /^\/api\/sets\/([\w-]+)\/assignments$/.exec(p)) && m === 'POST') return send(res, 200, Sets.addAssignments(db, r[1], (await body(req)).source_ids));
    if ((r = /^\/api\/sets\/([\w-]+)\/assignments\/([\w-]+)$/.exec(p))) {
      if (m === 'GET') return send(res, 200, Sets.getSetDraft(db, r[1], r[2]));
      if (m === 'PUT') return send(res, 200, Sets.saveSetDraft(db, r[1], r[2], await body(req)));
      if (m === 'PATCH') return send(res, 200, Sets.setQueueStatus(db, r[1], r[2], (await body(req)).queue_status));
    }
    if ((r = /^\/api\/sets\/([\w-]+)\/assignments\/([\w-]+)\/complete$/.exec(p)) && m === 'POST') return send(res, 200, Sets.completeAssignment(db, r[1], r[2], await body(req)));
    if ((r = /^\/api\/sets\/([\w-]+)\/submit$/.exec(p)) && m === 'POST') return send(res, 200, Sets.submitSet(db, r[1]));
    if ((r = /^\/api\/sets\/([\w-]+)\/revisions\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, 200, Sets.readForComparison(db, r[1], r[2], { viewerSetId: url.searchParams.get('viewer_set') ?? undefined }) ?? {});
    if (p === '/api/agreement' && m === 'GET') return send(res, 200, Sets.agreementReport(db, url.searchParams.get('a'), url.searchParams.get('b'), { viewerSetId: url.searchParams.get('viewer_set') ?? undefined }));
    // ---- Identity lineage (§6) and physical actions (§4) ----
    if (p === '/api/person-lineage') {
      if (m === 'GET') return send(res, 200, Lin.personLineage(db, { setId: url.searchParams.get('set') ?? 'primary' }));
      if (m === 'POST') return send(res, 201, Lin.addPersonRelation(db, await body(req)));
    }
    if (p === '/api/physical-actions') {
      if (m === 'GET') return send(res, 200, { items: Lin.listPhysicalActions(db, { source_id: url.searchParams.get('source') ?? null, include_inactive: url.searchParams.get('all') === '1' }), coverage: Lin.actionCoverage(db) });
      if (m === 'POST') return send(res, 201, Lin.createPhysicalAction(db, await body(req)));
    }
    if (p === '/api/physical-actions/merge' && m === 'POST') { const b = await body(req); return send(res, 201, Lin.mergeActions(db, b.action_ids, b)); }
    if ((r = /^\/api\/physical-actions\/([\w-]+)$/.exec(p))) {
      if (m === 'GET') return send(res, 200, Lin.getPhysicalAction(db, r[1]));
      if (m === 'PATCH') { const b = await body(req); return send(res, 200, Lin.setActionState(db, r[1], b.lineage_state, b)); }
    }
    if ((r = /^\/api\/physical-actions\/([\w-]+)\/occurrences$/.exec(p)) && m === 'POST') return send(res, 201, Lin.linkOccurrence(db, r[1], await body(req)));
    if ((r = /^\/api\/physical-actions\/([\w-]+)\/split$/.exec(p)) && m === 'POST') { const b = await body(req); return send(res, 201, Lin.splitAction(db, r[1], b.groups, b)); }
    if ((r = /^\/api\/action-occurrences\/([\w-]+)\/retire$/.exec(p)) && m === 'POST') return send(res, 200, Lin.retireOccurrence(db, r[1], await body(req)));
    if ((r = /^\/api\/sources\/([\w-]+)\/sport-suggestion$/.exec(p)) && m === 'POST') return send(res, 200, S.suggestSourceSport(db, r[1], await body(req)));
    if ((r = /^\/api\/sources\/([\w-]+)\/sport-suggestion\/confirm$/.exec(p)) && m === 'POST') { const b = await body(req); return send(res, 200, S.confirmSuggestedSport(db, r[1], { acknowledgeIncompatible: !!b.acknowledge_incompatible, remap: b.remap ?? null })); }
    if ((r = /^\/api\/sources\/([\w-]+)\/sports$/.exec(p))) {
      if (m === 'GET') return send(res, 200, S.listSourceSports(db, r[1]));
      if (m === 'POST') return send(res, 200, S.addSourceSport(db, r[1], (await body(req)).sport_id));
    }
    if ((r = /^\/api\/sources\/([\w-]+)\/states$/.exec(p)) && m === 'GET') return send(res, 200, A.sourceStates(db, r[1]));
    if ((r = /^\/api\/sources\/([\w-]+)\/revisions$/.exec(p)) && m === 'GET') return send(res, 200, { items: A.listRevisions(db, r[1]) });
    if ((r = /^\/api\/revisions\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, 200, A.getRevision(db, r[1]));
    if (m === 'GET' && p === '/api/batches') return send(res, 200, { items: db.prepare(`select b.id,b.label,b.created_at,count(distinct o.source_id) sources from upload_batches b left join upload_occurrences o on o.batch_id=b.id group by b.id order by b.created_at desc`).all() });
    if (m === 'POST' && p === '/api/ingestion/reconcile') {
      const b = await body(req);
      return startJob(res, () => reconcile(ctx, { roots: ctx.roots, deep: !!b.deep }));
    }
    if ((r = /^\/api\/jobs\/([\w-]+)$/.exec(p)) && m === 'GET') return send(res, jobs.has(r[1]) ? 200 : 404, jobs.get(r[1]) ?? { code: 'NOT_FOUND' });
    if (m === 'POST' && p === '/api/archive/verify') return send(res, 200, await verifyArchives(ctx));
    if (p === '/api/athletes') {
      if (m === 'GET') return send(res, 200, { items: A.listAthletes(db) });
      if (m === 'POST') { const b = await body(req); return send(res, 201, A.createAthlete(db, b.label, b.notes)); }
    }
    if ((r = /^\/api\/athletes\/([\w-]+)$/.exec(p)) && m === 'PATCH') { const b = await body(req); A.renameAthlete(db, r[1], b.label, b.notes); return send(res, 200, { ok: true }); }
    if ((r = /^\/api\/sources\/([\w-]+)\/appearances$/.exec(p))) {
      if (m === 'GET') return send(res, 200, { items: A.listSourceAppearances(db, r[1]) });
      if (m === 'POST') { const b = await body(req); return send(res, 201, A.addAppearance(db, b.athlete_id, r[1], { uncertain: !!b.uncertain })); }
    }
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
      if (m === 'POST') { const b = await body(req); return send(res, 201, b.schema === 'predictions/v1' ? I.importPipelinePredictions(db, b) : E.importPredictions(db, b)); }
      if (m === 'GET') return send(res, 200, { items: db.prepare('select id,run_id,pipeline_version,digest,created_at from pipeline_predictions order by created_at desc').all() });
    }
    if (p === '/api/evaluations') {
      if (m === 'POST') { const o = E.runEvaluation(db, await body(req)); return send(res, 201, { id: o.id, digest: o.digest }); }
      if (m === 'GET') return send(res, 200, { items: E.listEvaluations(db) });
    }
    if ((r = /^\/api\/evaluations\/([\w-]+)\/review$/.exec(p)) && m === 'GET') return send(res, 200, Rv.reviewEvaluation(db, r[1]));
    if ((r = /^\/api\/evaluations\/([\w-]+)$/.exec(p)) && m === 'GET') { const e = db.prepare('select report,digest from evaluation_runs where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND'); return send(res, 200, { digest: e.digest, report: JSON.parse(e.report) }); }
    if (m === 'POST' && p === '/api/imports/edl') { const b = await body(req); return send(res, 201, I.importEdl(db, b.edl ?? b)); }
    if (m === 'POST' && p === '/api/imports/predictions') return send(res, 201, I.importPipelinePredictions(db, await body(req)));
    // Read-only by design: running a backup writes to an operator-chosen path, so it is a CLI action, never an HTTP one.
    // One-time move of an existing local Studio into this (empty) database: the local export, verified table by table.
    // restoreBackup refuses a non-empty database, so this can never overwrite catalog data.
    if (m === 'POST' && p === '/api/admin/import-backup') {
      const backup = await body(req);
      if (backup?.format !== BACKUP_FORMAT) throw new ApiError('INVALID_INPUT', 'קובץ ייצוא לא מוכר');
      try { return send(res, 200, restoreBackup(db, backup, { actor: 'operator:migration' })); }
      catch (e) { throw new ApiError(/non-empty/.test(e.message) ? 'IMPORT_TARGET_NOT_EMPTY' : 'INVALID_INPUT', e.message); }
    }
    if (m === 'GET' && p === '/api/backup/status') return send(res, 200, ctx.serverless ? { state: 'managed', provider: 'supabase' } : backupStatus(db));
    if (m === 'POST' && p === '/api/integrity/verify') return send(res, 200, verifyIntegrity(db));
    if (m === 'GET' && p === '/api/outputs') return send(res, 200, { items: db.prepare('select id,output_id,run_id,source_id,created_at,payload from edl_records order by created_at desc').all().map(e => { const x = JSON.parse(e.payload); return { id: e.id, output_id: e.output_id, run_id: e.run_id, source_id: e.source_id, mode: x.mode, has_video: !!x.output_file, mapping: x.mapping ?? 'verified', output: x.output, source: x.source }; }) });
    if ((r = /^\/api\/outputs\/([\w-]+)\/edl$/.exec(p)) && m === 'GET') { const e = db.prepare('select payload from edl_records where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND'); return send(res, 200, JSON.parse(e.payload)); }
    if ((r = /^\/api\/outputs\/([\w-]+)\/review$/.exec(p)) && m === 'GET') {
      const e = db.prepare('select payload,source_id from edl_records where id=?').get(r[1]); if (!e) throw new ApiError('NOT_FOUND');
      const edl = JSON.parse(e.payload), g = I.gtBySha(db, edl);
      const sources = {};
      for (const sha of I.edlShas(edl)) {
        const src = I.sourceBySha(db, sha);
        if (src && src.ingest_state === 'ready') sources[sha] = { id: src.id, name: src.display_name, fps_num: src.fps_num, fps_den: src.fps_den, width: src.width, height: src.height, playback_url: src.proxy_path ? `/media/${src.id}/proxy` : `/media/${src.id}/original`, revision: g.revisions[sha] ?? null };
      }
      const single = Object.keys(g.bySha).length === 1 && I.edlShas(edl).length === 1;
      return send(res, 200, { edl, sources, unresolved: g.unresolved, revisions: g.revisions, source_id: single ? Object.values(g.revisions)[0].source_id : e.source_id,
        report: L.evaluateEditing(edl, { bySha: g.bySha }), ...L.frameEvidence(edl, { bySha: g.bySha }) });
    }
    if (m === 'POST' && p === '/api/editing/evaluate') {
      const b = await body(req);
      const rec = b.edl_id ? db.prepare('select payload from edl_records where id=?').get(b.edl_id) : null;
      const edl = rec ? JSON.parse(rec.payload) : null;
      const g = edl ? I.gtBySha(db, edl) : { bySha: {}, revisions: {}, unresolved: [] };
      const rep = L.evaluateEditing(edl, { bySha: g.bySha }, { thresholds: b.thresholds });
      const full = { ...rep, revisions: g.revisions, unresolved_sources: g.unresolved };
      const id = randomUUID();
      db.prepare('insert into editing_reports(id,edl_id,revision_id,evaluator_version,report,digest,created_at) values(?,?,?,?,?,?,?)').run(id, b.edl_id ?? null, Object.values(g.revisions).map(x => x.id).join(',') || null, rep.evaluator_version, JSON.stringify(full), A.digestOf(full), now());
      return send(res, 200, { id, report: full });
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

  /**
   * Long work (cloud sync, opening a video, identity check, ingest). Locally it runs in the background and the client polls
   * /api/jobs/<id>. On a serverless host there is no process that outlives the request (and the next poll may reach
   * another instance), so the work completes inside the request and the final state is returned directly.
   */
  async function startJob(res, work) {
    const id = randomUUID();
    if (ctx.serverless) {
      let j;
      try { j = { state: 'done', report: await work() }; } catch (e) { j = { state: 'failed', error: e.message, code: e.code }; }
      jobs.set(id, j);
      return send(res, 200, { job_id: id, ...j });
    }
    jobs.set(id, { state: 'running' });
    work().then(rep => jobs.set(id, { state: 'done', report: rep }), e => jobs.set(id, { state: 'failed', error: e.message }));
    return send(res, 202, { job_id: id });
  }

  async function media(req, res, id, kind) {
    if (ctx.serverless) {
      // Serverless: originals are played straight from R2 through a short-lived, read-only, pre-signed link; nothing
      // large passes through the function and the R2 credentials never reach the browser. No local derivatives exist.
      let key = null;
      if (kind === 'cloud-original') key = db.prepare('select key from cloud_objects where id=?').get(id)?.key ?? null;
      else if (kind === 'original' || kind === 'proxy') { const s = db.prepare('select provider, cloud_key from sources where id=?').get(id); if (s?.provider === 'cloud-r2') key = s.cloud_key; }
      if (!key || !ctx.cloud) return send(res, 404, { code: 'SOURCE_UNAVAILABLE' });
      // playback copy: the light 720p preview when it exists, otherwise the original (always correct, just heavy)
      const pk = kind === 'proxy' && ctx.previews ? await ctx.previews.find(key) : null;
      res.writeHead(302, { location: pk ? ctx.previews.bucket.presignGet(pk, 3600) : ctx.cloud.presignGet(key, 3600), 'cache-control': 'no-store', 'x-studio-media': pk ? 'preview' : 'original' });
      return res.end();
    }
    let file = null, archiveKey = null, reader = ctx.archive;
    if (kind === 'cloud-original') {                                   // /media/cloud/<object id>/original : a catalogued object (used while opening)
      const o = db.prepare('select key from cloud_objects where id=?').get(id);
      if (!o || !ctx.cloud) return send(res, 404, { code: 'NOT_FOUND' });
      archiveKey = o.key; reader = ctx.cloud; kind = 'original';
    } else if (kind === 'out') {
      const e = db.prepare('select payload from edl_records where id=?').get(id);
      const f = e && JSON.parse(e.payload).output_file;
      file = f && path.join(ctx.outputsDir, path.basename(f));
    } else {
      const s = db.prepare('select * from sources where id=?').get(id);
      if (!s) return send(res, 404, { code: 'NOT_FOUND' });
      if (kind === 'original' && s.provider === 'cloud-r2') { if (!ctx.cloud) return send(res, 503, { code: 'CLOUD_NOT_CONFIGURED' }); archiveKey = s.cloud_key; reader = ctx.cloud; }
      else if (kind === 'original') archiveKey = s.archive_key; else file = kind === 'thumb' ? s.thumb_path : s.proxy_path;
    }
    const type = kind === 'thumb' ? 'image/jpeg' : kind === 'original' ? 'video/mp4' : (MIME[path.extname(file ?? '')] ?? 'application/octet-stream');
    let size, open;
    if (archiveKey) {
      size = await reader.size(archiveKey);
      open = o => reader.open(archiveKey, o);
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
        res.writeHead(302, { location: '/', // Persistent (1 year) so the fixed address http://127.0.0.1:<port>/ keeps working after the browser is closed;
        // still HttpOnly + SameSite=Strict, and the server only listens on 127.0.0.1.
        'set-cookie': loginCookie(req) });
        return res.end();
      }
      // Login form (hosted): the access code is sent in a POST body, never in a URL that could land in access logs.
      if (url.pathname === '/auth/login' && req.method === 'POST') {
        if (req.headers.origin && !originOk(req.headers.origin)) return send(res, 403, { code: 'PERMISSION_DENIED' });
        let b = {}; try { b = await body(req); } catch { /* empty / invalid body = wrong code */ }
        if (typeof b.token !== 'string' || !safeEq(b.token.trim(), token)) {
          await new Promise(r => setTimeout(r, 400));   // slows guessing; the code is 192 bits anyway
          return send(res, 401, { code: 'PERMISSION_DENIED', message: 'קוד הכניסה שגוי' });
        }
        return send(res, 200, { ok: true }, { 'set-cookie': loginCookie(req) });
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) {
        if (!authed(req)) return send(res, 401, { code: 'PERMISSION_DENIED', message: new ApiError('PERMISSION_DENIED').he });
        if (req.method !== 'GET') {
          const o = req.headers.origin;
          if (o && !originOk(o)) return send(res, 403, { code: 'PERMISSION_DENIED' });
        }
        const cm = /^\/media\/cloud\/([\w-]+)\/original$/.exec(url.pathname);
        if (cm) return await media(req, res, cm[1], 'cloud-original');
        const mm = /^\/media\/([\w-]+)\/(proxy|thumb|original|out)$/.exec(url.pathname);
        if (mm) return await media(req, res, mm[1], mm[2]);
        return await api(req, res, url);
      }
      return serveStatic(res, url.pathname);
    } catch (e) {
      // a failure after the response started (e.g. a media stream whose source broke): the status line is gone, so
      // just end the connection instead of trying to write a second response (ERR_HTTP_HEADERS_SENT)
      if (res.headersSent) { console.error('[studio] error after response started:', e?.message); try { res.destroy(); } catch { /* already closed */ } return; }
      if (e instanceof ApiError) return send(res, e.status, { code: e.code, message: e.he, detail: e.message, unresolved: e.unresolved, incompatible: e.incompatible, conflicts: e.conflicts });
      if (/IMMUTABLE|PROTECTED/.test(e?.message ?? '')) return send(res, 409, { code: 'IMMUTABLE', message: 'רשומה בלתי ניתנת לשינוי' });
      console.error('[studio] internal error:', e?.message);
      return send(res, 500, { code: 'INTERNAL', message: 'שגיאה פנימית' });
    }
  });
}
