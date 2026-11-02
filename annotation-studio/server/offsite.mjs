import crypto from 'node:crypto';
// Local-first independent backup: a copy of the Ground Truth database and of the labelled original footage on a DIFFERENT PHYSICAL DEVICE.
// "Footage and its backup on the same disk" is not a backup, so this refuses a destination that shares a device with the live data.
//   - never deletes anything in the destination (additive; archive objects are write-once, DB exports are timestamped)
//   - every copied object is re-hashed before it is accepted; corrupt/missing destination copies are repaired on the next run
//   - records every run in the append-only audit log so the UI can warn when the last good backup is old or missing
import { mkdirSync, mkdtempSync, writeFileSync, readFileSync, existsSync, readdirSync, renameSync, rmSync, statSync, chmodSync, realpathSync, createWriteStream } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import os from 'node:os';
import { encryptFile, encryptBuffer, decryptStream, decryptFile, decryptToBuffer, sha256File, keyCheck, blindName, requireStrongKey, manifestMac } from './backupcrypto.mjs';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';
import { LocalArchive } from './archive.mjs';
import { exportBackup, restoreBackup, verifyBackupFile } from './backup.mjs';
import { digestOf } from './annotations.mjs';
import { audit, now } from './db.mjs';
import { rebuildDerivatives } from './ingest.mjs';

export const OFFSITE_FORMAT = 'gt-offsite/v1';
export const OFFSITE_FORMAT_V2 = 'gt-offsite/v2';
export const STALE_AFTER_DAYS = 7;

function deriveKey(keyInput) {
  return crypto.createHash('sha256').update(String(keyInput)).digest();
}

export function encryptPayload(text, keyInput) {
  const key = deriveKey(keyInput);
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const enc = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return JSON.stringify({
    cipher: 'aes-256-gcm',
    iv: iv.toString('base64'),
    tag: tag.toString('base64'),
    data: enc.toString('base64'),
  });
}

export function decryptPayload(payloadStr, keyInput) {
  const key = deriveKey(keyInput);
  const { iv, tag, data } = JSON.parse(payloadStr);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(tag, 'base64'));
  const dec = Buffer.concat([decipher.update(Buffer.from(data, 'base64')), decipher.final()]);
  return dec.toString('utf8');
}

export class BackupError extends Error { constructor(code, message) { super(message); this.code = code; } }

export const deviceOf = p => statSync(p).dev;

/**
 * Best-effort PHYSICAL disk identity (a different volume/partition on the same disk is not an independent backup).
 * Linux: /sys/dev/block/MAJ:MIN -> whole-disk node. Windows: drive letter -> Get-Partition DiskNumber. Otherwise null
 * (unknown) — the run then records `device_check: "volume_only"` so the operator report never overclaims.
 */
export function physicalDiskOf(p) {
  try {
    if (process.platform === 'linux') {
      const dev = statSync(p).dev; const maj = Math.floor(dev / 256) & 0xfff, min = (dev & 0xff) | ((Math.floor(dev / 4096)) & 0xfff00);
      const sys = realpathSync(`/sys/dev/block/${maj}:${min}`);
      return existsSync(path.join(sys, 'partition')) ? path.basename(path.dirname(sys)) : path.basename(sys);
    }
    if (process.platform === 'win32') {
      const letter = path.resolve(p).slice(0, 1).toUpperCase();
      const r = spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', `(Get-Partition -DriveLetter ${letter}).DiskNumber`], { encoding: 'utf8', timeout: 15000 });
      const n = String(r.stdout || '').trim();
      return r.status === 0 && /^\d+$/.test(n) ? `disk${n}` : null;
    }
  } catch { /* unknown */ }
  return null;
}

function liveRoots(ctx) {
  const roots = [ctx.home];
  if (ctx.archive.kind === 'local') roots.push(ctx.archive.root);
  return roots.filter(r => existsSync(r));
}

function labelledSources(db, scope) {
  const base = "select id, sha256, byte_size, archive_key from sources where ingest_state='ready' and archive_key is not null";
  return scope === 'all' ? db.prepare(`${base} order by id`).all()
    : db.prepare(`${base} and (id in (select source_id from annotation_drafts) or id in (select source_id from annotation_revisions)) order by id`).all();
}

function atomicWrite(file, data) {
  const t = `${file}.tmp-${process.pid}`;
  writeFileSync(t, data); renameSync(t, file);
}

/**
 * @param destDir      directory on another physical device (external drive, network share, mounted remote)
 * @param scope        'labelled' (default: footage that has ground truth) | 'all'
 * @param encryption_key  passphrase (>= 12 chars). REQUIRED unless `plaintext: 'device-encrypted'` attests that the
 *                     destination device itself is fully encrypted (BitLocker/FileVault/LUKS); that attestation is
 *                     recorded in the manifest and audit log.
 * @param allowSameDevice  tests only; the CLI never sets it
 */
export async function runOffsiteBackup(ctx, destDir, { scope = 'labelled', allowSameDevice = false, deviceOf: devFn = deviceOf, diskOf = physicalDiskOf, label = 'offsite', encryption_key = undefined, plaintext = undefined } = {}) {
  if (!['labelled', 'all'].includes(scope)) throw new BackupError('INVALID_SCOPE', 'scope must be labelled or all');
  const encKey = encryption_key ?? process.env.STUDIO_BACKUP_KEY;
  if (!encKey && plaintext !== 'device-encrypted') {
    throw new BackupError('BACKUP_ENCRYPTION_REQUIRED', 'גיבוי חייב להיות מוצפן: ספק מפתח (--key / STUDIO_BACKUP_KEY), או אשר במפורש שהדיסק היעד מוצפן במלואו (--plaintext-device-encrypted)');
  }
  if (encKey) requireStrongKey(encKey);
  mkdirSync(destDir, { recursive: true });
  const live = liveRoots(ctx);
  if (!allowSameDevice && new Set(live.map(devFn)).has(devFn(destDir))) {
    throw new BackupError('BACKUP_SAME_DEVICE', 'destination is on the same device as the live data; a backup on the same disk does not protect against disk failure');
  }
  let deviceCheck = 'volume_only';
  const destDisk = diskOf(destDir), liveDisks = live.map(diskOf);
  if (destDisk && liveDisks.every(Boolean)) {
    if (!allowSameDevice && liveDisks.includes(destDisk)) throw new BackupError('BACKUP_SAME_DISK', 'destination is a different volume but on the SAME physical disk as the live data');
    deviceCheck = liveDisks.includes(destDisk) ? 'same_disk_allowed_in_tests' : 'distinct_physical_disk';
  }
  return encKey
    ? runEncrypted(ctx, destDir, { scope, label, encKey, deviceCheck })
    : runPlaintext(ctx, destDir, { scope, label, deviceCheck });
}

async function runPlaintext(ctx, destDir, { scope, label, deviceCheck }) {
  if (existsSync(path.join(destDir, 'KEYINFO.json'))) throw new BackupError('BACKUP_MODE_MISMATCH', 'היעד מכיל גיבוי מוצפן — אין לכתוב אליו גיבוי לא מוצפן');
  mkdirSync(path.join(destDir, 'db'), { recursive: true });
  const dst = new LocalArchive(path.join(destDir, 'archive'));
  const result = { scope, db_file: null, db_digest: null, copied: 0, skipped: 0, repaired: 0, failed: [], objects: [], encrypted: false, device_check: deviceCheck, plaintext_attestation: 'device-encrypted' };
  const exp = exportBackup(ctx.db);
  const stamp = now().replace(/[:.]/g, '-');
  const dbFileName = `gt-${stamp}.json`;
  const dbFile = path.join(destDir, 'db', dbFileName);
  atomicWrite(dbFile, JSON.stringify(exp));
  const reread = JSON.parse(readFileSync(dbFile, 'utf8'));
  if (verifyBackupFile(reread).length || reread.digest !== exp.digest) throw new BackupError('BACKUP_DB_UNVERIFIED', 'database export failed re-read verification');
  result.db_file = dbFileName; result.db_digest = exp.digest;
  mkdirSync(path.join(destDir, 'sqlite'), { recursive: true });
  const sqliteName = `gt-${stamp}.sqlite`, sqlitePath = path.join(destDir, 'sqlite', sqliteName);
  try {
    ctx.db.prepare('VACUUM INTO ?').run(sqlitePath);
    result.sqlite_file = sqliteName; result.sqlite_sha256 = await sha256File(sqlitePath);
  } catch { /* PostgreSQL backend: logical export only */ }
  for (const s of labelledSources(ctx.db, scope)) {
    const key = dst.keyFor(s.sha256);
    const had = await dst.size(key);
    if ((await dst.verify(key, s.sha256, s.byte_size)).ok) { result.skipped++; result.objects.push({ sha256: s.sha256, size: s.byte_size }); continue; }
    const sv = await ctx.archive.verify(s.archive_key, s.sha256, s.byte_size);
    if (!sv.ok) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: `source_${sv.reason}` }); continue; }
    const t = path.join(destDir, `.incoming-${s.sha256.slice(0, 12)}`);
    try {
      await pipeline(await ctx.archive.open(s.archive_key), createWriteStream(t));
      await dst.put(t, s.sha256, s.byte_size);
      result.copied++; if (had != null) result.repaired++;
      result.objects.push({ sha256: s.sha256, size: s.byte_size });
    } catch (e) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: e.code ?? 'copy_failed' }); }
    finally { rmSync(t, { force: true }); }
  }
  const manifest = { format: OFFSITE_FORMAT, created_at: now(), scope, db_file: result.db_file, db_digest: result.db_digest, encrypted: false, plaintext_attestation: 'device-encrypted', device_check: deviceCheck, sqlite_file: result.sqlite_file ?? null, sqlite_sha256: result.sqlite_sha256 ?? null, objects: result.objects.sort((a, b) => (a.sha256 < b.sha256 ? -1 : 1)) };
  atomicWrite(path.join(destDir, 'MANIFEST.json'), JSON.stringify({ ...manifest, digest: digestOf(manifest) }));
  return finish(ctx, label, result);
}

function finish(ctx, label, result) {
  const ok = result.failed.length === 0;
  // only counts and a label are recorded (never the destination path or the key)
  audit(ctx.db, 'system', ok ? 'offsite_backup' : 'offsite_backup_failed', label, { scope: result.scope, copied: result.copied, skipped: result.skipped, repaired: result.repaired, failed: result.failed.length, objects: result.objects.length, db_digest: result.db_digest, encrypted: !!result.encrypted, device_check: result.device_check });
  return { ok, ...result };
}

/** v2: every artifact on the medium is AES-256-GCM encrypted; object names are blinded; the key never touches disk. */
async function runEncrypted(ctx, destDir, { scope, label, encKey, deviceCheck }) {
  const keyInfoPath = path.join(destDir, 'KEYINFO.json');
  let keyInfo;
  if (existsSync(keyInfoPath)) {
    keyInfo = JSON.parse(readFileSync(keyInfoPath, 'utf8'));
    if (keyCheck(encKey, keyInfo.salt) !== keyInfo.key_check) throw new BackupError('BACKUP_KEY_MISMATCH', 'המפתח שסופק שונה מהמפתח של גיבוי קיים ביעד זה — השתמש במפתח המקורי או ביעד חדש');
  } else {
    const salt = crypto.randomBytes(16).toString('hex');
    keyInfo = { format: 'gt-keyinfo/v1', kdf: 'scrypt(N=32768,r=8,p=1)', cipher: 'aes-256-gcm', salt, key_check: keyCheck(encKey, salt), created_at: now() };
    atomicWrite(keyInfoPath, JSON.stringify(keyInfo));
  }
  for (const d of ['db', 'sqlite', 'objects']) mkdirSync(path.join(destDir, d), { recursive: true });
  const result = { scope, db_file: null, db_digest: null, copied: 0, skipped: 0, repaired: 0, failed: [], objects: [], encrypted: true, device_check: deviceCheck };
  const stamp = now().replace(/[:.]/g, '-');
  const work = mkdtempSync(path.join(ctx.home, '.backup-work-'));
  try {
    // 1. logical export, encrypted and verified by decrypt + digest before acceptance
    const exp = exportBackup(ctx.db);
    const dbFile = path.join(destDir, 'db', `gt-${stamp}.json.enc`);
    atomicWrite(dbFile, encryptBuffer(Buffer.from(JSON.stringify(exp)), encKey));
    const back = JSON.parse((await decryptToBuffer(dbFile, encKey)).toString('utf8'));
    if (verifyBackupFile(back).length || back.digest !== exp.digest) throw new BackupError('BACKUP_DB_UNVERIFIED', 'encrypted database export failed re-read verification');
    result.db_file = path.basename(dbFile); result.db_digest = exp.digest; result.db_cipher_sha256 = await sha256File(dbFile);
    // 2. physical SQLite snapshot: written ONLY inside the live home, encrypted onto the medium, plaintext removed
    try {
      const snap = path.join(work, 'snapshot.sqlite');
      ctx.db.prepare('VACUUM INTO ?').run(snap);
      const enc = await encryptFile(snap, path.join(destDir, 'sqlite', `gt-${stamp}.sqlite.enc`), encKey);
      const check = await decryptStream(path.join(destDir, 'sqlite', `gt-${stamp}.sqlite.enc`), encKey);
      if (check.plain_sha256 !== enc.plain_sha256) throw new BackupError('BACKUP_DB_UNVERIFIED', 'encrypted SQLite snapshot failed verification');
      result.sqlite_file = `gt-${stamp}.sqlite.enc`; result.sqlite_sha256 = enc.plain_sha256; result.sqlite_cipher_sha256 = enc.cipher_sha256;
    } catch (e) { if (e instanceof BackupError) throw e; /* PostgreSQL backend: logical export only */ }
    // 3. footage
    const index = [];
    for (const s of labelledSources(ctx.db, scope)) {
      const name = blindName(encKey, keyInfo.salt, s.sha256);
      const target = path.join(destDir, 'objects', `${name}.enc`);
      const had = existsSync(target);
      if (had) {
        try {
          const v = await decryptStream(target, encKey);
          if (v.plain_sha256 === s.sha256 && v.plain_size === s.byte_size) {
            result.skipped++; result.objects.push({ name, size: s.byte_size, cipher_sha256: await sha256File(target) }); index.push({ name, sha256: s.sha256, size: s.byte_size }); continue;
          }
        } catch { /* corrupt or tampered: repaired below */ }
      }
      const sv = await ctx.archive.verify(s.archive_key, s.sha256, s.byte_size);
      if (!sv.ok) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: `source_${sv.reason}` }); continue; }
      const plainTmp = path.join(work, `src-${s.sha256.slice(0, 12)}`);
      const encTmp = path.join(destDir, 'objects', `.incoming-${name.slice(0, 12)}.enc`);
      try {
        await pipeline(await ctx.archive.open(s.archive_key), createWriteStream(plainTmp));
        const enc = await encryptFile(plainTmp, encTmp, encKey);
        const v = await decryptStream(encTmp, encKey);                       // never trust a write: decrypt and re-hash
        if (enc.plain_sha256 !== s.sha256 || v.plain_sha256 !== s.sha256 || v.plain_size !== s.byte_size) throw Object.assign(new Error('hash'), { code: 'hash_mismatch' });
        if (had) { chmodSync(target, 0o644); rmSync(target, { force: true }); }  // replace only a copy proven corrupt above
        renameSync(encTmp, target); chmodSync(target, 0o444);
        result.copied++; if (had) result.repaired++;
        result.objects.push({ name, size: s.byte_size, cipher_sha256: enc.cipher_sha256 }); index.push({ name, sha256: s.sha256, size: s.byte_size });
      } catch (e) { result.failed.push({ sha256: s.sha256.slice(0, 12), reason: e.code ?? 'copy_failed' }); rmSync(encTmp, { force: true }); }
      finally { rmSync(plainTmp, { force: true }); }
    }
    // 4. encrypted object index (blind name -> sha256) and a digest-covered plaintext manifest with no footage hashes
    const idxFile = path.join(destDir, `INDEX-${stamp}.json.enc`);
    atomicWrite(idxFile, encryptBuffer(Buffer.from(JSON.stringify(index.sort((a, b) => (a.name < b.name ? -1 : 1)))), encKey));
    const manifest = { format: OFFSITE_FORMAT_V2, created_at: now(), scope, encrypted: true, cipher: keyInfo.cipher, kdf: keyInfo.kdf, key_salt: keyInfo.salt, key_check: keyInfo.key_check, device_check: deviceCheck,
      db_file: result.db_file, db_digest: result.db_digest, db_cipher_sha256: result.db_cipher_sha256,
      sqlite_file: result.sqlite_file ?? null, sqlite_sha256: result.sqlite_sha256 ?? null, sqlite_cipher_sha256: result.sqlite_cipher_sha256 ?? null,
      index_file: path.basename(idxFile), index_cipher_sha256: await sha256File(idxFile),
      objects: result.objects.sort((a, b) => (a.name < b.name ? -1 : 1)) };
    const dg = digestOf(manifest);
    // Keyed MAC: without the passphrase nobody can re-point the manifest at an older (still decryptable) DB/index file.
    atomicWrite(path.join(destDir, 'MANIFEST.json'), JSON.stringify({ ...manifest, digest: dg, mac: manifestMac(encKey, keyInfo.salt, dg) }));
  } finally { rmSync(work, { recursive: true, force: true }); }
  return finish(ctx, label, result);
}

/** Plaintext files on the medium that would leak footage/state (legacy v1 runs or stray copies). */
export function plaintextArtifacts(destDir) {
  const out = [];
  const walk = (d, rel = '') => { if (!existsSync(d)) return; for (const n of readdirSync(d)) { const p = path.join(d, n), r = path.join(rel, n); if (statSync(p).isDirectory()) walk(p, r); else if (!n.endsWith('.enc') && !['MANIFEST.json', 'KEYINFO.json'].includes(n)) out.push(r.replace(/\\/g, '/')); } };
  for (const d of ['db', 'sqlite', 'archive', 'objects']) walk(path.join(destDir, d), d);
  return out;
}

/** Re-reads everything in a backup directory and checks it against its manifest (v2: decrypt + re-hash with the key). */
export async function verifyOffsite(destDir, { encryption_key = undefined, deep = true } = {}) {
  const mf = path.join(destDir, 'MANIFEST.json');
  if (!existsSync(mf)) return { ok: false, problems: ['manifest_missing'] };
  const m = JSON.parse(readFileSync(mf, 'utf8'));
  if (m.format !== OFFSITE_FORMAT_V2) return verifyOffsiteV1(destDir, { encryption_key });
  const { digest, mac, ...body } = m;
  const problems = [], warnings = [];
  if (digestOf(body) !== digest) problems.push('manifest_digest_mismatch');
  const encKey = encryption_key ?? process.env.STUDIO_BACKUP_KEY;
  const leaks = plaintextArtifacts(destDir);
  if (leaks.length) problems.push(`plaintext_artifacts_present:${leaks.length}`);   // unencrypted sensitive files on the medium
  const file = (dir, n) => path.join(destDir, dir, n ?? '');
  const cipherOk = async (f, h, tag) => { if (!existsSync(f)) { problems.push(`${tag}_missing`); return false; } if (h && (await sha256File(f)) !== h) { problems.push(`${tag}_cipher_mismatch`); return false; } return true; };
  // Without a key we can still prove the ciphertext is intact; with the key we prove it decrypts to the right content.
  const dbOk = await cipherOk(file('db', body.db_file), body.db_cipher_sha256, 'db_file');
  const idxOk = await cipherOk(path.join(destDir, body.index_file ?? ''), body.index_cipher_sha256, 'index_file');
  if (body.sqlite_file) await cipherOk(file('sqlite', body.sqlite_file), body.sqlite_cipher_sha256, 'sqlite_file');
  for (const o of body.objects) await cipherOk(file('objects', `${o.name}.enc`), o.cipher_sha256, `object:${o.name.slice(0, 12)}`);
  let key_verified = false;
  if (!encKey) problems.push('encryption_key_required');
  else if (keyCheck(encKey, body.key_salt) !== body.key_check) problems.push('encryption_key_wrong');
  else if (manifestMac(encKey, body.key_salt, digest) !== mac) problems.push('manifest_mac_mismatch');
  else if (deep) {
    key_verified = true;
    try {
      if (dbOk) {
        const dbj = JSON.parse((await decryptToBuffer(file('db', body.db_file), encKey)).toString('utf8'));
        problems.push(...verifyBackupFile(dbj).map(x => `db:${x}`));
        if (dbj.digest !== body.db_digest) problems.push('db_digest_differs_from_manifest');
      }
      if (body.sqlite_file && existsSync(file('sqlite', body.sqlite_file))) {
        // Decrypt into a private temp dir (never onto the backup medium) and prove the snapshot is a sound database.
        const t = mkdtempSync(path.join(os.tmpdir(), 'gt-verify-'));
        try {
          const out = path.join(t, 'snap.sqlite');
          const r = await decryptFile(file('sqlite', body.sqlite_file), out, encKey);
          if (r.plain_sha256 !== body.sqlite_sha256) problems.push('sqlite_sha256_mismatch');
          const sq = new DatabaseSync(out, { readOnly: true });
          try { const ic = sq.prepare('pragma integrity_check').get(); if (Object.values(ic)[0] !== 'ok') problems.push('sqlite_integrity_failed'); } finally { sq.close(); }
        } finally { rmSync(t, { recursive: true, force: true }); }
      }
      const index = idxOk ? JSON.parse((await decryptToBuffer(path.join(destDir, body.index_file), encKey)).toString('utf8')) : [];
      const byName = new Map(index.map(x => [x.name, x]));
      for (const o of body.objects) {
        const f = file('objects', `${o.name}.enc`); const ix = byName.get(o.name);
        if (!ix) { problems.push(`object:${o.name.slice(0, 12)}:not_in_index`); continue; }
        if (!existsSync(f)) continue;
        try { const v = await decryptStream(f, encKey); if (v.plain_sha256 !== ix.sha256 || v.plain_size !== ix.size) problems.push(`object:${o.name.slice(0, 12)}:hash_mismatch`); }
        catch (e) { problems.push(`object:${o.name.slice(0, 12)}:${e.code ?? 'decrypt_failed'}`); }
      }
    } catch (e) { problems.push(`decrypt:${e.code ?? e.message}`); }
  }
  return { ok: problems.length === 0, problems, warnings, objects: body.objects.length, created_at: body.created_at, scope: body.scope, encrypted: true, key_verified, device_check: body.device_check };
}

/** Restore drill / disaster recovery: EMPTY database + EMPTY archive <- backup. Verifies (with the key) before and after. */
export async function restoreFromOffsite(ctx, destDir, { encryption_key = undefined } = {}) {
  const mf = path.join(destDir, 'MANIFEST.json');
  const m = existsSync(mf) ? JSON.parse(readFileSync(mf, 'utf8')) : null;
  if (!m || m.format !== OFFSITE_FORMAT_V2) return restoreFromOffsiteV1(ctx, destDir, { encryption_key });
  const encKey = encryption_key ?? process.env.STUDIO_BACKUP_KEY;
  if (!encKey) throw new BackupError('KEY_REQUIRED', 'קובץ הגיבוי מוצפן — נדרש מפתח הצפנה לשחזור');
  const v = await verifyOffsite(destDir, { encryption_key: encKey });
  if (!v.ok) throw new BackupError(v.problems.includes('encryption_key_wrong') ? 'BACKUP_KEY_WRONG' : 'BACKUP_UNVERIFIED', `backup failed verification: ${v.problems.slice(0, 3).join(', ')}`);
  const { digest, mac, ...body } = m;
  const dbj = JSON.parse((await decryptToBuffer(path.join(destDir, 'db', body.db_file), encKey)).toString('utf8'));
  if (ctx.db.prepare('select count(*) n from sources').get().n > 0) throw new BackupError('RESTORE_TARGET_NOT_EMPTY', 'restore only into an EMPTY Studio home/database');
  // Footage FIRST (content-addressed, hash-verified, idempotent), database LAST: a failure part-way leaves an empty
  // database, so the restore can simply be retried — never a restored database pointing at a partial archive.
  const index = JSON.parse((await decryptToBuffer(path.join(destDir, body.index_file), encKey)).toString('utf8'));
  let objects = 0;
  for (const ix of index) {
    const t = path.join(ctx.home, `.restore-${ix.name.slice(0, 12)}`);
    try { await decryptFile(path.join(destDir, 'objects', `${ix.name}.enc`), t, encKey); await ctx.archive.put(t, ix.sha256, ix.size); objects++; }
    finally { rmSync(t, { force: true }); }
  }
  restoreBackup(ctx.db, dbj);                                            // refuses to merge into a non-empty database
  return finishRestore(ctx, objects);
}

async function finishRestore(ctx, objects) {
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

// Legacy v1 (plaintext layout, optional encrypted JSON export).
async function verifyOffsiteV1(destDir, { encryption_key = undefined } = {}) {
  const problems = [];
  const mf = path.join(destDir, 'MANIFEST.json');
  if (!existsSync(mf)) return { ok: false, problems: ['manifest_missing'] };
  const { digest, ...body } = JSON.parse(readFileSync(mf, 'utf8'));
  if (digestOf(body) !== digest) problems.push('manifest_digest_mismatch');
  const dbPath = path.join(destDir, 'db', body.db_file ?? '');
  const encKey = encryption_key ?? process.env.STUDIO_BACKUP_KEY;
  if (!existsSync(dbPath)) problems.push('db_file_missing');
  else {
    try {
      let rawText = readFileSync(dbPath, 'utf8');
      if (body.encrypted || body.db_file?.endsWith('.enc')) {
        if (!encKey) { problems.push('encryption_key_required'); }
        else { rawText = decryptPayload(rawText, encKey); }
      }
      if (!problems.includes('encryption_key_required')) {
        const dbj = JSON.parse(rawText);
        const p = verifyBackupFile(dbj);
        if (p.length) problems.push(...p.map(x => `db:${x}`));
        if (dbj.digest !== body.db_digest) problems.push('db_digest_differs_from_manifest');
      }
    } catch (e) {
      problems.push(`db_read_error:${e.message}`);
    }
  }
  if (body.sqlite_file) {
    const sqPath = path.join(destDir, 'sqlite', body.sqlite_file);
    if (!existsSync(sqPath)) problems.push('sqlite_file_missing');
    else if (body.sqlite_sha256) {
      const h = crypto.createHash('sha256').update(readFileSync(sqPath)).digest('hex');
      if (h !== body.sqlite_sha256) problems.push('sqlite_sha256_mismatch');
    }
  }
  const arch = new LocalArchive(path.join(destDir, 'archive'));
  for (const o of body.objects) { const r = await arch.verify(arch.keyFor(o.sha256), o.sha256, o.size); if (!r.ok) problems.push(`object:${o.sha256.slice(0, 12)}:${r.reason}`); }
  return { ok: problems.length === 0, problems, objects: body.objects.length, created_at: body.created_at, scope: body.scope };
}

/** Restore drill / disaster recovery: empty database + empty archive <- backup directory. Verifies before and after. */
async function restoreFromOffsiteV1(ctx, destDir, { encryption_key = undefined } = {}) {
  const v = await verifyOffsiteV1(destDir, { encryption_key });
  if (!v.ok) throw new BackupError('BACKUP_UNVERIFIED', `backup failed verification: ${v.problems.slice(0, 3).join(', ')}`);
  const { digest, ...body } = JSON.parse(readFileSync(path.join(destDir, 'MANIFEST.json'), 'utf8'));
  const encKey = encryption_key ?? process.env.STUDIO_BACKUP_KEY;
  let rawText = readFileSync(path.join(destDir, 'db', body.db_file), 'utf8');
  if (body.encrypted || body.db_file?.endsWith('.enc')) {
    if (!encKey) throw new BackupError('KEY_REQUIRED', 'קובץ הגיבוי מוצפן — נדרש מפתח הצפנה לשחזור');
    rawText = decryptPayload(rawText, encKey);
  }
  const dbj = JSON.parse(rawText);
  restoreBackup(ctx.db, dbj);
  const src = new LocalArchive(path.join(destDir, 'archive'));
  let objects = 0;
  for (const o of body.objects) {
    const tmp = path.join(ctx.home, `.restore-${o.sha256.slice(0, 12)}`);
    await pipeline(await src.open(src.keyFor(o.sha256)), createWriteStream(tmp));
    try { await ctx.archive.put(tmp, o.sha256, o.size); objects++; } finally { rmSync(tmp, { force: true }); }
  }
  return finishRestore(ctx, objects);
}

/** What the UI shows: when did the last complete external backup happen, and was anything left uncopied? */
export function backupStatus(db, { nowMs = Date.now() } = {}) {
  const last = db.prepare("select at, action, detail from audit_log where action in ('offsite_backup','offsite_backup_failed') order by id desc limit 1").get();
  const lastOk = db.prepare("select at, detail from audit_log where action='offsite_backup' order by id desc limit 1").get();
  if (!lastOk) return { state: 'never', last_failed: last?.action === 'offsite_backup_failed', stale_after_days: STALE_AFTER_DAYS };
  const ageDays = (nowMs - Date.parse(lastOk.at)) / 86400000;
  return { state: ageDays > STALE_AFTER_DAYS ? 'stale' : 'ok', last_ok_at: lastOk.at, age_days: Math.round(ageDays * 10) / 10,
    last_failed: last?.action === 'offsite_backup_failed', counts: JSON.parse(lastOk.detail ?? '{}'), stale_after_days: STALE_AFTER_DAYS,
    encrypted: JSON.parse(lastOk.detail ?? '{}').encrypted === true, device_check: JSON.parse(lastOk.detail ?? '{}').device_check ?? 'unknown' };
}
