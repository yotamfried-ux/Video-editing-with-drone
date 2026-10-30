// Protected source archive. Interface = {put, path, verify}. The local implementation is
// content-addressed and write-once; an R2 implementation (separate bucket + credentials)
// is a drop-in once the operator approves creating that resource.
import { createReadStream, createWriteStream, mkdirSync, existsSync, renameSync, chmodSync, rmSync, statSync, readdirSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';

export async function sha256File(file) {
  const h = createHash('sha256');
  await pipeline(createReadStream(file), h);
  return h.digest('hex');
}

export class LocalArchive {
  kind = 'local';
  constructor(root) { this.root = root; mkdirSync(root, { recursive: true }); }
  keyFor(sha) { return `${sha.slice(0, 2)}/${sha}`; }
  pathFor(key) { return path.join(this.root, key); }

  /** Copy bytes, re-hash the COPY, and only publish it if it equals the expected hash. */
  async put(srcPath, expectedSha, expectedSize) {
    const key = this.keyFor(expectedSha);
    const dest = this.pathFor(key);
    if (existsSync(dest) && (await this.verify(key, expectedSha, expectedSize)).ok) return key;
    mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = path.join(this.root, `.incoming-${randomUUID()}`);
    try {
      await pipeline(createReadStream(srcPath), createWriteStream(tmp));
      const got = await sha256File(tmp);
      const size = statSync(tmp).size;
      if (got !== expectedSha || size !== expectedSize) {
        throw Object.assign(new Error(`archive copy mismatch (sha ${got.slice(0, 12)}…, ${size} bytes)`), { code: 'ARCHIVE_UNVERIFIED' });
      }
      if (existsSync(dest)) { try { chmodSync(dest, 0o644); } catch {} rmSync(dest, { force: true }); }
      renameSync(tmp, dest);
      chmodSync(dest, 0o444);
      return key;
    } finally { rmSync(tmp, { force: true }); }
  }

  async size(key) { const p = this.pathFor(key); return existsSync(p) ? statSync(p).size : null; }
  async open(key, { start, end } = {}) { return createReadStream(this.pathFor(key), start != null ? { start, end } : undefined); }
  async list() {
    const out = [];
    for (const d of existsSync(this.root) ? readdirSync(this.root, { withFileTypes: true }) : []) {
      if (!d.isDirectory()) continue;
      for (const f of readdirSync(path.join(this.root, d.name))) out.push({ key: `${d.name}/${f}`, size: statSync(path.join(this.root, d.name, f)).size });
    }
    return out;
  }

  async verify(key, expectedSha, expectedSize) {
    const p = this.pathFor(key);
    if (!existsSync(p)) return { ok: false, reason: 'missing' };
    const size = statSync(p).size;
    if (expectedSize != null && size !== expectedSize) return { ok: false, reason: 'size_mismatch' };
    const got = await sha256File(p);
    return got === expectedSha ? { ok: true } : { ok: false, reason: 'hash_mismatch' };
  }
}
