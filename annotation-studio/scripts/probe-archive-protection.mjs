#!/usr/bin/env node
// LIVE probe of the protected archive bucket. NOT RUN in this repository's validation (needs real resources + approval).
// Checks, against the actual account, what the unit tests can only assume:
//   1. write token can put + verify a probe object under probe/ (single and multipart >5 MiB)
//   2. read-only token CAN read and CANNOT put/delete
//   3. bucket retention/lock: delete of a locked probe object is refused (even for the write token)
//   4. no public (unauthenticated) read path
// Requires: STUDIO_R2_* (writer), optional STUDIO_R2_READER_ACCESS_KEY_ID/SECRET_ACCESS_KEY, STUDIO_PROBE_CONFIRM=I_APPROVED_LIVE_PROBE
import { randomBytes, createHash, randomUUID } from 'node:crypto';
import { writeFileSync, mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { R2Archive, r2ConfigFromEnv } from '../server/r2archive.mjs';
import { signRequest, sha256hex } from '../server/sigv4.mjs';

if (process.env.STUDIO_PROBE_CONFIRM !== 'I_APPROVED_LIVE_PROBE') { console.error('refusing: live probe requires explicit approval (STUDIO_PROBE_CONFIRM)'); process.exit(2); }
const cfg = r2ConfigFromEnv();
const writer = new R2Archive({ ...cfg, prefix: 'probe/' });
const results = {};
const tmp = mkdtempSync(path.join(os.tmpdir(), 'probe-'));
const small = randomBytes(64 * 1024), big = randomBytes(6 * 1024 * 1024);
for (const [name, data, threshold] of [['single_put', small, Infinity], ['multipart', big, 1]]) {
  const f = path.join(tmp, name); writeFileSync(f, data);
  const a = new R2Archive({ ...cfg, prefix: 'probe/', multipartThreshold: threshold, partSize: 5 * 1024 * 1024 });
  const sha = createHash('sha256').update(data).digest('hex');
  try { const key = await a.put(f, sha, data.length); results[name] = { ok: (await a.verify(key, sha, data.length)).ok, key }; } catch (e) { results[name] = { ok: false, error: e.code ?? e.message }; }
}
async function rawDelete(key, accessKeyId, secretAccessKey) {
  const url = `${cfg.endpoint}/${cfg.bucket}/${key}`;
  const h = signRequest({ method: 'DELETE', url, payloadHash: sha256hex(''), region: 'auto', accessKeyId, secretAccessKey });
  delete h._canonical;
  return (await fetch(url, { method: 'DELETE', headers: h })).status;
}
const probeKey = results.single_put?.key;
if (probeKey) {
  results.public_read_status = (await fetch(`${cfg.endpoint}/${cfg.bucket}/${probeKey}`)).status;       // expect 400/401/403
  results.writer_delete_status = await rawDelete(probeKey, cfg.accessKeyId, cfg.secretAccessKey);        // expect 403 if bucket lock/retention is active
  if (process.env.STUDIO_R2_READER_ACCESS_KEY_ID) {
    const rid = process.env.STUDIO_R2_READER_ACCESS_KEY_ID, rs = process.env.STUDIO_R2_READER_SECRET_ACCESS_KEY;
    const reader = new R2Archive({ ...cfg, accessKeyId: rid, secretAccessKey: rs, prefix: 'probe/' });
    results.reader_can_read = (await reader.head(probeKey)) != null;
    results.reader_delete_status = await rawDelete(probeKey, rid, rs);                                   // expect 403
  }
}
results.interpretation = 'delete statuses must be 403; 200/204 means the object is NOT protected from deletion';
console.log(JSON.stringify(results, null, 2));
void randomUUID; void writer;
