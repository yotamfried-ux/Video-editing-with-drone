// Authenticated encryption for every artifact written to backup media (spec §22.2 P0-2).
//
// File format "GTENC2" (streamable, constant memory, suitable for multi-GB 4K originals):
//   magic   6 bytes  "GTENC2"
//   salt   16 bytes  scrypt salt (fresh per file)
//   iv     12 bytes  AES-GCM nonce (fresh per file)
//   data    n bytes  AES-256-GCM ciphertext
//   tag    16 bytes  GCM authentication tag (trailer)
// Key = scrypt(passphrase, salt, N=2^15, r=8, p=1, 32 bytes). The passphrase is never written anywhere; a wrong key or
// any modified byte fails GCM authentication, which is reported as BACKUP_KEY_OR_DATA_INVALID — never as a partial file.
import crypto from 'node:crypto';
import { createReadStream, createWriteStream, openSync, readSync, closeSync, statSync, renameSync, rmSync } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { Transform, Writable } from 'node:stream';

export const MAGIC = Buffer.from('GTENC2');
const HDR = MAGIC.length + 16 + 12, TAG = 16;
const SCRYPT = { N: 1 << 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
const keyCache = new Map();

export class CryptoError extends Error { constructor(code, message) { super(message); this.code = code; } }

export function requireStrongKey(passphrase) {
  if (typeof passphrase !== 'string' || passphrase.length < 12) {
    throw new CryptoError('BACKUP_KEY_WEAK', 'מפתח הגיבוי חייב להכיל לפחות 12 תווים');
  }
}
function deriveKey(passphrase, salt) {
  const id = `${salt.toString('hex')}`;
  const cached = keyCache.get(id);
  if (cached && cached.pass === passphrase) return cached.key;
  const key = crypto.scryptSync(String(passphrase), salt, 32, SCRYPT);
  keyCache.set(id, { pass: passphrase, key });
  if (keyCache.size > 256) keyCache.delete(keyCache.keys().next().value);
  return key;
}

/** Encrypt `src` (path) into `dst` (path) atomically; returns { plain_sha256, plain_size, cipher_sha256, cipher_size }. */
export async function encryptFile(src, dst, passphrase) {
  const salt = crypto.randomBytes(16), iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', deriveKey(passphrase, salt), iv);
  const plainHash = crypto.createHash('sha256'), cipherHash = crypto.createHash('sha256');
  let plainSize = 0;
  const tmp = `${dst}.tmp-${process.pid}-${Date.now()}`;
  const out = createWriteStream(tmp);
  const header = Buffer.concat([MAGIC, salt, iv]);
  cipherHash.update(header);
  await new Promise((res, rej) => out.write(header, e => (e ? rej(e) : res())));
  try {
    await pipeline(
      createReadStream(src),
      new Transform({ transform(chunk, _e, cb) { plainHash.update(chunk); plainSize += chunk.length; cb(null, chunk); } }),
      cipher,
      new Transform({
        transform(chunk, _e, cb) { cipherHash.update(chunk); cb(null, chunk); },
        flush(cb) { const tag = cipher.getAuthTag(); cipherHash.update(tag); cb(null, tag); },
      }),
      out,
    );
    renameSync(tmp, dst);
  } catch (e) { rmSync(tmp, { force: true }); throw e; }
  return { plain_sha256: plainHash.digest('hex'), plain_size: plainSize, cipher_sha256: cipherHash.digest('hex'), cipher_size: statSync(dst).size };
}

export function encryptBuffer(buf, passphrase) {
  const salt = crypto.randomBytes(16), iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', deriveKey(passphrase, salt), iv);
  return Buffer.concat([MAGIC, salt, iv, cipher.update(buf), cipher.final(), cipher.getAuthTag()]);
}

function readHeaderAndTag(file) {
  const size = statSync(file).size;
  if (size < HDR + TAG) throw new CryptoError('BACKUP_KEY_OR_DATA_INVALID', 'קובץ מוצפן קטוע או פגום');
  const fd = openSync(file, 'r');
  try {
    const hdr = Buffer.alloc(HDR), tag = Buffer.alloc(TAG);
    readSync(fd, hdr, 0, HDR, 0); readSync(fd, tag, 0, TAG, size - TAG);
    if (!hdr.subarray(0, MAGIC.length).equals(MAGIC)) throw new CryptoError('BACKUP_FORMAT_UNKNOWN', 'הקובץ אינו בפורמט גיבוי מוצפן מוכר');
    return { size, salt: hdr.subarray(MAGIC.length, MAGIC.length + 16), iv: hdr.subarray(MAGIC.length + 16, HDR), tag };
  } finally { closeSync(fd); }
}

/**
 * Decrypt `file` streaming into `sink` (a Writable) or, when `sink` is null, only authenticate and hash it.
 * Returns { plain_sha256, plain_size }. Throws BACKUP_KEY_OR_DATA_INVALID on a wrong key or any tampering; callers must
 * treat everything written to `sink` before that error as garbage (decryptFile writes to a temp file and only renames
 * after successful authentication).
 */
export async function decryptStream(file, passphrase, sink = null) {
  const { size, salt, iv, tag } = readHeaderAndTag(file);
  const decipher = crypto.createDecipheriv('aes-256-gcm', deriveKey(passphrase, salt), iv);
  decipher.setAuthTag(tag);
  const h = crypto.createHash('sha256'); let n = 0;
  const tap = new Transform({ transform(chunk, _e, cb) { h.update(chunk); n += chunk.length; cb(null, chunk); } });
  const end = sink ?? new Writable({ write(_c, _e, cb) { cb(); } });
  try {
    await pipeline(createReadStream(file, { start: HDR, end: size - TAG - 1 }), decipher, tap, end);
  } catch (e) {
    if (e instanceof CryptoError) throw e;
    throw new CryptoError('BACKUP_KEY_OR_DATA_INVALID', 'פענוח הגיבוי נכשל: מפתח שגוי או קובץ שעבר שינוי/נפגם');
  }
  return { plain_sha256: h.digest('hex'), plain_size: n };
}

export async function decryptFile(file, dst, passphrase) {
  const tmp = `${dst}.tmp-${process.pid}-${Date.now()}`;
  try {
    const r = await decryptStream(file, passphrase, createWriteStream(tmp));
    renameSync(tmp, dst);
    return r;
  } catch (e) { rmSync(tmp, { force: true }); throw e; }
}

export async function decryptToBuffer(file, passphrase) {
  const chunks = [];
  await decryptStream(file, passphrase, new Writable({ write(c, _e, cb) { chunks.push(c); cb(); } }));
  return Buffer.concat(chunks);
}

export async function sha256File(file) {
  const h = crypto.createHash('sha256');
  await pipeline(createReadStream(file), new Writable({ write(c, _e, cb) { h.update(c); cb(); } }));
  return h.digest('hex');
}

/** Non-secret key fingerprint for "same key as last time?" checks: HMAC over a fixed label with a per-backup salt. */
export function keyCheck(passphrase, saltHex) {
  const k = crypto.scryptSync(String(passphrase), Buffer.from(saltHex, 'hex'), 32, SCRYPT);
  return crypto.createHmac('sha256', k).update('sportreel-gt-backup-key-check/v1').digest('hex');
}
/** Object names on the medium must not reveal footage hashes: HMAC(sha256) under a key derived from the passphrase. */
export function blindName(passphrase, saltHex, sha256) {
  const k = deriveKey(passphrase, Buffer.from(saltHex, 'hex'));
  return crypto.createHmac('sha256', k).update(`object:${sha256}`).digest('hex');
}

/** Keyed MAC over the manifest digest (prevents rollback/re-pointing by someone without the passphrase). */
export function manifestMac(passphrase, saltHex, digest) {
  const k = deriveKey(passphrase, Buffer.from(saltHex, 'hex'));
  return crypto.createHmac('sha256', k).update(`manifest:${digest}`).digest('hex');
}
