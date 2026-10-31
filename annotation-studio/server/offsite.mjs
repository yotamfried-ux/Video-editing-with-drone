// Local-first independent backup: a copy of the Ground Truth database and of the labelled original footage on a DIFFERENT PHYSICAL DEVICE.
// "Footage and its backup on the same disk" is not a backup, so this refuses a destination that shares a device with the live data.
//   - never deletes anything in the destination (additive; archive objects are write-once, DB exports are timestamped)
//   - every copied object is re-hashed before it is accepted; corrupt/missing destination copies are repaired on the next run
//   - records every run in the append-only audit log so the UI can warn when the last good backup is old or missing
import { mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, renameSync, rmSync, statSync, createWriteStream } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';
import { LocalArchive } from './archive.mjs';
import { exportBackup, restoreBackup, verifyBackupFile } from './backup.mjs';
import { digestOf } from './annotations.mjs';
import { audit, now } from './db.mjs';
import { rebuildDerivatives } from './ingest.mjs';

export const OFFSITE_FORMAT = 'gt-offsite/v1';
export const STALE_AFTER_DAYS = 7;

export class BackupError extends Error { constructor(code, message) { super(message); this.code = code; } }

export const deviceOf = p => statSync(p).dev;

function liveDevices(ctx, devFn) {
  const roots = [ctx.home];
  if (ctx.archive.kind === 'local') roots.push(ctx.archive.root);
  return new Set(roots.filter(r => existsSync(r)).map(devFn));
}

function labelledSources(db, scope) {
  const base = "select id, sha256, byte_size, archive_key from sources where ingest_state='ready' and archive_key is not null";
  return scope === 'all' ? db.prepare(`${base} order by id`).all()
    : db.prepare(`${base} and (id in (select source_id from annotation_drafts) or id in (select source_id from annotation_revisions)) order by id`).all();
}

function atomicWrite(file, text) {
  const tmp = `${file}.tmp-${process.pid}`;
  writeFileSync(tmp, text); renameSync(tmp, file);
}

/**
 * @param destDir      directory on another physical device (external drive, network share, mounted remote)
 * @param scope        'labelled' (default: footage that has ground truth) | 'all'
 * @param allowSameDevice  tests only; the CLI never sets it
 */
export async function runOffsiteBackup(ctx, destDir, { scope = 'labelled', allowSameDevice = false, deviceOf: devFn = deviceOf, label = 'offsite' } = {}) {
  if (!['labelled', 'all'].includes(scope)) throw new BackupError('INVALID_SCOPE', 'scope must be labelled or all');
  mkdirSync(destDir, { recursive: true });
  if (!allowSameDevice && liveDevices(ctx, devFn).has(devFn(destDir))) {
    throw new BackupError('BACKUP_SAME_DEVICE', 'destination is on the same device as the live data; a backup on the same disk does not protect against disk failure');
  }
  mkdirSync(path.join(destDir, 'db'), { recursive: true });
  const dst = new LocalArchive(path.join(destDir, 'archive'));
  const result = { scope, db_file: null, db_digest: null, copied: 0, skipped: 0, repaired: 0, failed: [], objects: [] };

  // 1. database export, re-read and verified before it is accepted
  const exp = exportBackup(ctx.db);
  const stamp = now().replace(/[:.]/g, '-');
  const dbFile = path.join(destDir, 'db', `gt-${stamp}.json`);
  atomicWrite(dbFile, JSON.stringify(exp));
  const reread = JSON.parse(readFileSync(dbFile, 'utf8'));
  if (verifyBackupFile(reread).length || reread.digest !== exp.digest) throw new BackupError('BACKUP_DB_UNVERIFIED', 'database export failed re-read verification');
  result.db_file = path.basename(dbFile); result.db_digest = exp.digest;

  // 2. footage: copy what is missing or corrupt, only from sources whose own archive copy verifies
  for (const s of labelledSources(ctx.db, scope)) {
    const key = dst.keyFor(s.sha256);
    const had = await dst.size(key);
    if ((await dst.verify(key, s.sha256, s.byte_size)).ok) { result.skipped++; result.objects.push({ sha256: s.sha256, size: s.byte_size }); continue; }
    const sv = await ctx.archive.verify(s.archive_key, s.sha256, s.byte_size);
    if (!sv.ok) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: `source_${sv.reason}` }); continue; }
    const tmp = path.join(destDir, `.incoming-${s.sha256.slice(0, 12)}`);
    try {
      await pipeline(await ctx.archive.open(s.archive_key), createWriteStream(tmp));
      await dst.put(tmp, s.sha256, s.byte_size);                      // hash-verifies the copy before publishing it
      result.copied++; if (had != null) result.repaired++;
      result.objects.push({ sha256: s.sha256, size: s.byte_size });
    } catch (e) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: e.code ?? 'copy_failed' }); }
    finally { rmSync(tmp, { force: true }); }
  }

  // 3. manifest (digest-covered) describing exactly what this backup holds
  const manifest = { format: OFFSITE_FORMAT, created_at: now(), scope, db_file: result.db_file, db_digest: result.db_digest, objects: result.objects.sort((a, b) => a.sha256 < b.sha256 ? -1 : 1) };
  atomicWrite(path.join(destDir, 'MANIFEST.json'), JSON.stringify({ ...manifest, digest: digestOf(manifest) }));

  const ok = result.failed.length === 0;
  // only the counts and a label are recorded (never the destination path)
  audit(ctx.db, 'system', ok ? 'offsite_backup' : 'offsite_backup_failed', label, { scope, copied: result.copied, skipped: result.skipped, repaired: result.repaired, failed: result.failed.length, objects: result.objects.length, db_digest: result.db_digest });
  return { ok, ...result };
}

/** Re-reads everything in a backup directory and checks it against its manifest. */
export async function verifyOffsite(destDir) {
  const problems = [];
  const mf = path.join(destDir, 'MANIFEST.json');
  if (!existsSync(mf)) return { ok: false, problems: ['manifest_missing'] };
  const { digest, ...body } = JSON.parse(readFileSync(mf, 'utf8'));
  if (digestOf(body) !== digest) problems.push('manifest_digest_mismatch');
  const dbPath = path.join(destDir, 'db', body.db_file ?? '');
  if (!existsSync(dbPath)) problems.push('db_file_missing');
  else { const dbj = JSON.parse(readFileSync(dbPath, 'utf8')); const p = verifyBackupFile(dbj); if (p.length) problems.push(...p.map(x => `db:${x}`)); if (dbj.digest !== body.db_digest) problems.push('db_digest_differs_from_manifest'); }
  const arch = new LocalArchive(path.join(destDir, 'archive'));
  for (const o of body.objects) { const r = await arch.verify(arch.keyFor(o.sha256), o.sha256, o.size); if (!r.ok) problems.push(`object:${o.sha256.slice(0, 12)}:${r.reason}`); }
  return { ok: problems.length === 0, problems, objects: body.objects.length, created_at: body.created_at, scope: body.scope };
}

/** Restore drill / disaster recovery: empty database + empty archive <- backup directory. Verifies before and after. */
export async function restoreFromOffsite(ctx, destDir) {
  const v = await verifyOffsite(destDir);
  if (!v.ok) throw new BackupError('BACKUP_UNVERIFIED', `backup failed verification: ${v.problems.slice(0, 3).join(', ')}`);
  const { digest, ...body } = JSON.parse(readFileSync(path.join(destDir, 'MANIFEST.json'), 'utf8'));
  const dbj = JSON.parse(readFileSync(path.join(destDir, 'db', body.db_file), 'utf8'));
  restoreBackup(ctx.db, dbj);
  const src = new LocalArchive(path.join(destDir, 'archive'));
  let objects = 0;
  for (const o of body.objects) {
    const tmp = path.join(ctx.home, `.restore-${o.sha256.slice(0, 12)}`);
    await pipeline(await src.open(src.keyFor(o.sha256)), createWriteStream(tmp));
    try { await ctx.archive.put(tmp, o.sha256, o.size); objects++; } finally { rmSync(tmp, { force: true }); }
  }
  // Sources whose original is NOT in this backup (e.g. unlabelled footage under the default scope) must not claim to be ready:
  // mark them unavailable. Identity is unchanged, so `reconcile` re-archives them from operational storage when they reappear.
  let unavailable = 0;
  for (const r of ctx.db.prepare("select id,sha256,byte_size,archive_key from sources where archive_key is not null").all()) {
    if (!(await ctx.archive.verify(r.archive_key, r.sha256, r.byte_size)).ok) {
      ctx.db.prepare("update sources set ingest_state='unavailable', archive_error='not_in_restored_backup' where id=?").run(r.id); unavailable++;
    }
  }
  // derivatives lived in the old cache: forget the stale paths and rebuild from the restored originals
  ctx.db.prepare('update sources set thumb_path=null, proxy_path=null').run();
  const derivatives = await rebuildDerivatives(ctx);
  return { restored_objects: objects, unavailable_sources: unavailable, derivatives };
}

/** What the UI shows: when did the last complete external backup happen, and was anything left uncopied? */
export function backupStatus(db, { nowMs = Date.now() } = {}) {
  const last = db.prepare("select at, action, detail from audit_log where action in ('offsite_backup','offsite_backup_failed') order by id desc limit 1").get();
  const lastOk = db.prepare("select at, detail from audit_log where action='offsite_backup' order by id desc limit 1").get();
  if (!lastOk) return { state: 'never', last_failed: last?.action === 'offsite_backup_failed', stale_after_days: STALE_AFTER_DAYS };
  const ageDays = (nowMs - Date.parse(lastOk.at)) / 86400000;
  return { state: ageDays > STALE_AFTER_DAYS ? 'stale' : 'ok', last_ok_at: lastOk.at, age_days: Math.round(ageDays * 10) / 10,
    last_failed: last?.action === 'offsite_backup_failed', counts: JSON.parse(lastOk.detail ?? '{}'), stale_after_days: STALE_AFTER_DAYS };
}
