// Protected source archive on S3-compatible storage (Cloudflare R2). Same contract as LocalArchive.
//
// Safety properties (all covered by tests against an in-repo S3 stub; a live probe script exists but has NOT been run):
//  * There is NO delete/overwrite-of-original method: this class cannot remove or replace an archived object.
//  * Every upload carries the content SHA-256 (x-amz-content-sha256 + x-amz-checksum-sha256) so the server rejects corrupt bytes.
//  * `verify` re-reads the object and hashes it; `put` returns only after verification succeeds.
//  * Credentials come from the environment/constructor only; they are never logged or included in error messages.
import { createReadStream, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { Readable } from 'node:stream';
import { signRequest, sha256hex } from './sigv4.mjs';

export class ArchiveError extends Error { constructor(code, message) { super(message); this.code = code; } }

const MIB = 1024 * 1024;

export function r2ConfigFromEnv(env = process.env) {
  const need = n => { if (!env[n]) throw new ArchiveError('ARCHIVE_CONFIG', `${n} is not set`); return env[n]; };
  return {
    endpoint: env.STUDIO_R2_ENDPOINT || `https://${need('STUDIO_R2_ACCOUNT_ID')}.r2.cloudflarestorage.com`,
    bucket: need('STUDIO_R2_BUCKET'),
    accessKeyId: need('STUDIO_R2_ACCESS_KEY_ID'),
    secretAccessKey: need('STUDIO_R2_SECRET_ACCESS_KEY'),
    prefix: env.STUDIO_R2_PREFIX ?? 'sources/',
  };
}

export class R2Archive {
  kind = 'r2';
  constructor({ endpoint, bucket, accessKeyId, secretAccessKey, region = 'auto', prefix = 'sources/', partSize = 64 * MIB, multipartThreshold = 256 * MIB, fetchImpl = fetch, retries = 3 }) {
    for (const [k, v] of Object.entries({ endpoint, bucket, accessKeyId, secretAccessKey })) if (!v) throw new ArchiveError('ARCHIVE_CONFIG', `${k} required`);
    // Held in closure-private fields so accidental JSON/log serialization of the object cannot leak them.
    const secret = { accessKeyId, secretAccessKey };
    this.#sign = (args) => signRequest({ ...args, region, service: 's3', ...secret });
    this.endpoint = endpoint.replace(/\/+$/, ''); this.bucket = bucket; this.prefix = prefix;
    this.partSize = partSize; this.multipartThreshold = multipartThreshold; this.fetch = fetchImpl; this.retries = retries;
  }
  #sign;
  toJSON() { return { kind: 'r2', bucket: this.bucket, prefix: this.prefix }; }

  keyFor(sha) { return `${this.prefix}${sha.slice(0, 2)}/${sha}`; }
  #url(key, query = '') { return `${this.endpoint}/${this.bucket}/${key.split('/').map(encodeURIComponent).join('/')}${query}`; }

  async #request(method, key, { query = '', headers = {}, body, payloadHash, expect = [200] } = {}) {
    let last;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      const url = this.#url(key, query);
      const signed = this.#sign({ method, url, headers, payloadHash: payloadHash ?? sha256hex('') });
      const { _canonical, ...hdrs } = signed;
      try {
        const init = { method, headers: hdrs };
        if (body !== undefined) { init.body = body; init.duplex = 'half'; }
        const res = await this.fetch(url, init);
        if (expect.includes(res.status)) return res;
        const text = await res.text().catch(() => '');
        const retriable = res.status >= 500 || res.status === 429;
        last = new ArchiveError(res.status === 404 ? 'ARCHIVE_NOT_FOUND' : retriable ? 'ARCHIVE_RETRYABLE' : 'ARCHIVE_REJECTED',
          `storage ${method} returned ${res.status}${/BadDigest|checksum/i.test(text) ? ' (checksum mismatch)' : ''}`);
        if (!retriable) throw last;
      } catch (e) {
        if (e instanceof ArchiveError && e.code !== 'ARCHIVE_RETRYABLE') throw e;
        last = e instanceof ArchiveError ? e : new ArchiveError('ARCHIVE_RETRYABLE', 'storage request failed');
      }
      // body streams cannot be replayed: callers pass a factory-based body only via #putSingle which re-creates it
      if (typeof body === 'object' && body !== null && !Buffer.isBuffer(body)) break;
      await new Promise(r => setTimeout(r, 20 * 2 ** attempt));
    }
    throw last;
  }

  async head(key) {
    try { const r = await this.#request('HEAD', key, { expect: [200] }); return { size: Number(r.headers.get('content-length')) }; }
    catch (e) { if (e.code === 'ARCHIVE_NOT_FOUND') return null; throw e; }
  }
  async size(key) { return (await this.head(key))?.size ?? null; }

  /** Streams the object (optionally a byte range). Used for authenticated playback; no public URL exists. */
  async open(key, { start, end } = {}) {
    const headers = start != null ? { range: `bytes=${start}-${end ?? ''}` } : {};
    const r = await this.#request('GET', key, { headers, expect: [200, 206] });
    return Readable.fromWeb(r.body);
  }

  async verify(key, expectedSha, expectedSize) {
    const h = await this.head(key);
    if (!h) return { ok: false, reason: 'missing' };
    if (expectedSize != null && h.size !== expectedSize) return { ok: false, reason: 'size_mismatch' };
    const hash = createHash('sha256');
    for await (const chunk of await this.open(key)) hash.update(chunk);
    return hash.digest('hex') === expectedSha ? { ok: true } : { ok: false, reason: 'hash_mismatch' };
  }

  async put(srcPath, expectedSha, expectedSize) {
    const key = this.keyFor(expectedSha);
    if ((await this.head(key)) && (await this.verify(key, expectedSha, expectedSize)).ok) return key;     // idempotent
    const size = statSync(srcPath).size;
    if (size !== expectedSize) throw new ArchiveError('ARCHIVE_UNVERIFIED', 'source size changed during archiving');
    if (size >= this.multipartThreshold) await this.#putMultipart(srcPath, key, expectedSha, size);
    else await this.#putSingle(srcPath, key, expectedSha, size);
    const v = await this.verify(key, expectedSha, expectedSize);
    if (!v.ok) throw new ArchiveError('ARCHIVE_UNVERIFIED', `archived copy failed verification (${v.reason})`);
    return key;
  }

  async #putSingle(srcPath, key, sha, size) {
    const b64 = Buffer.from(sha, 'hex').toString('base64');
    await this.#request('PUT', key, {
      headers: { 'content-length': String(size), 'content-type': 'application/octet-stream', 'x-amz-checksum-sha256': b64 },
      payloadHash: sha, body: Readable.toWeb(createReadStream(srcPath)), expect: [200],
    });
  }

  async #putMultipart(srcPath, key, sha, size) {
    const init = await (await this.#request('POST', key, { query: '?uploads', headers: { 'content-type': 'application/octet-stream' }, expect: [200] })).text();
    const uploadId = /<UploadId>([^<]+)<\/UploadId>/.exec(init)?.[1];
    if (!uploadId) throw new ArchiveError('ARCHIVE_REJECTED', 'multipart init failed');
    const parts = [];
    try {
      let n = 0, buf = [], have = 0;
      const flush = async () => {
        const data = Buffer.concat(buf); buf = []; have = 0; n++;
        const ph = createHash('sha256').update(data).digest();
        const r = await this.#request('PUT', key, { query: `?partNumber=${n}&uploadId=${encodeURIComponent(uploadId)}`,
          headers: { 'content-length': String(data.length), 'x-amz-checksum-sha256': ph.toString('base64') }, payloadHash: ph.toString('hex'), body: data, expect: [200] });
        parts.push({ n, etag: r.headers.get('etag') });
      };
      for await (const chunk of createReadStream(srcPath, { highWaterMark: Math.min(8 * MIB, this.partSize) })) {
        buf.push(chunk); have += chunk.length;
        if (have >= this.partSize) await flush();
      }
      if (have) await flush();
      const xml = `<CompleteMultipartUpload>${parts.map(p => `<Part><PartNumber>${p.n}</PartNumber><ETag>${p.etag}</ETag></Part>`).join('')}</CompleteMultipartUpload>`;
      await this.#request('POST', key, { query: `?uploadId=${encodeURIComponent(uploadId)}`, headers: { 'content-type': 'application/xml' }, payloadHash: sha256hex(xml), body: Buffer.from(xml), expect: [200] });
    } catch (e) {
      await this.#request('DELETE', key, { query: `?uploadId=${encodeURIComponent(uploadId)}`, expect: [200, 204, 404] }).catch(() => {});   // abort upload (never an object delete)
      throw e;
    }
  }

  /** Lists archived objects (for mirroring/audits). */
  async list() {
    const out = []; let token = '';
    do {
      const q = `?list-type=2&prefix=${encodeURIComponent(this.prefix)}${token ? `&continuation-token=${encodeURIComponent(token)}` : ''}`;
      const xml = await (await this.#request('GET', '', { query: q, expect: [200] })).text();
      for (const m of xml.matchAll(/<Contents><Key>([^<]+)<\/Key>(?:<LastModified>[^<]*<\/LastModified>)?(?:<ETag>[^<]*<\/ETag>)?<Size>(\d+)<\/Size>/g)) out.push({ key: m[1], size: Number(m[2]) });
      token = /<NextContinuationToken>([^<]+)<\/NextContinuationToken>/.exec(xml)?.[1] ?? '';
    } while (token);
    return out;
  }

  /** Abort multipart uploads left behind by interrupted ingestion (storage hygiene; touches no completed object). */
  async abortIncompleteUploads() {
    const xml = await (await this.#request('GET', '', { query: `?uploads&prefix=${encodeURIComponent(this.prefix)}`, expect: [200] })).text();
    let n = 0;
    for (const m of xml.matchAll(/<Upload><Key>([^<]+)<\/Key><UploadId>([^<]+)<\/UploadId>/g)) {
      await this.#request('DELETE', m[1], { query: `?uploadId=${encodeURIComponent(m[2])}`, expect: [200, 204, 404] }); n++;
    }
    return n;
  }
}

/** Copy every object missing (or corrupt) in `dst` from `src`, verifying hashes. Used for the second-copy backup of the archive. */
export async function mirrorArchive(src, dst, { tmpDir }) {
  const { mkdtempSync, rmSync, createWriteStream } = await import('node:fs');
  const { pipeline } = await import('node:stream/promises');
  const path = await import('node:path');
  const res = { copied: 0, skipped: 0, failed: [] };
  const dir = mkdtempSync(path.join(tmpDir, 'mirror-'));
  try {
    for (const { key, size } of await src.list()) {
      const sha = key.split('/').pop();
      if (!/^[0-9a-f]{64}$/.test(sha)) { res.failed.push({ key, reason: 'not_content_addressed' }); continue; }
      if ((await dst.verify(dst.keyFor(sha), sha, size)).ok) { res.skipped++; continue; }
      const sv = await src.verify(key, sha, size);
      if (!sv.ok) { res.failed.push({ key, reason: `source_${sv.reason}` }); continue; }
      const tmp = path.join(dir, sha);
      await pipeline(await src.open(key), createWriteStream(tmp));
      try { await dst.put(tmp, sha, size); res.copied++; } catch (e) { res.failed.push({ key, reason: e.code ?? 'put_failed' }); }
      rmSync(tmp, { force: true });
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
  return res;
}
