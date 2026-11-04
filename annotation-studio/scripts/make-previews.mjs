// Creates the light playback copies (720p, frame for frame) of the cloud originals, on THIS computer, and stores them
// in the EXISTING bucket under studio/previews/ only.
//   node --env-file=.studio-cloud.env --env-file=.studio-previews.env scripts/make-previews.mjs [--only <text>] [--dry-run]
// Reads originals with the Studio's read-only key (STUDIO_CLOUD_R2_*). Writes with a temporary credential that R2
// itself limits to PutObject under studio/previews/ (derived per hour from STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID /
// _SECRET_ACCESS_KEY, which is never sent anywhere). Create-once: an existing preview is skipped, never overwritten;
// nothing is ever deleted; originals cannot be written, replaced or deleted with that credential.
import os from 'node:os'; import path from 'node:path'; import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { CloudBucket, cloudConfigFromEnv, SOURCE_PREFIXES } from '../server/cloud.mjs';
import { previewKey, makePreview, putPreview, previewWriteCredentials } from '../server/previews.mjs';
import { probeMp4, rangeReaderForCloud } from '../server/mp4probe.mjs';

const argv = process.argv.slice(2), flag = n => argv.includes(n), val = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const env = process.env, die = m => { console.error(`X  ${m}`); process.exit(1); };
const src = cloudConfigFromEnv(env); if (!src) die('STUDIO_CLOUD_R2_* is not set (use --env-file=.studio-cloud.env)');
const parent = { id: env.STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID, secret: env.STUDIO_PREVIEW_PARENT_SECRET_ACCESS_KEY };
if (!flag('--dry-run') && (!parent.id || !parent.secret)) die('STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID / _SECRET_ACCESS_KEY are not set (see HOSTED-SETUP: they only sign a credential limited to studio/previews/)');
if (parent.id && parent.id === src.accessKeyId) die('the parent key must not be the Studio read-only key (it cannot sign write credentials)');
const accountId = env.STUDIO_CLOUD_R2_ACCOUNT_ID || (new URL(src.endpoint).host.split('.')[0]);
const originals = new CloudBucket(src);
let creds = null;
const writeCreds = () => {                                   // renewed before it expires; 1 hour each
  if (!creds || creds.expiresAt - Date.now() < 10 * 60 * 1000) creds = previewWriteCredentials({ endpoint: src.endpoint, accountId, parentAccessKeyId: parent.id, parentSecretAccessKey: parent.secret, bucket: src.bucket, ttlSeconds: 3600 });
  return creds;
};
const include = (val('--only') ?? env.STUDIO_CLOUD_INCLUDE ?? '').trim().toLowerCase();
const all = (await Promise.all(SOURCE_PREFIXES.map(p => originals.list(p)))).flat()
  .filter(o => /\.(mp4|mov|m4v)$/i.test(o.key) && (!include || o.key.toLowerCase().includes(include)));
console.log(`${all.length} originals${include ? ` matching "${include}"` : ''} -> ${src.bucket}/studio/previews/`);
let made = 0, skipped = 0, failed = 0;
for (const o of all) {
  const key = previewKey(o.key);
  try {
    if (await originals.head(key).catch(() => null)) { skipped++; console.log(`=  ${key} (exists)`); continue; }
    const meta = await probeMp4(rangeReaderForCloud(originals, o.key), o.size);
    if (flag('--dry-run')) { console.log(`?  ${o.key} -> ${key}: ${meta.width}x${meta.height} ${meta.frame_count} frames (dry run, nothing written)`); continue; }
    const dir = mkdtempSync(path.join(os.tmpdir(), 'preview-')), out = path.join(dir, 'p.mp4');
    try {
      const t0 = Date.now();
      // live proof for every video: the original's size and ETag are read before and re-checked after the upload
      const before = await originals.head(o.key);
      await makePreview(originals.presignGet(o.key, 6 * 3600), out, meta);
      const r = await putPreview({ endpoint: src.endpoint, bucket: src.bucket, creds: writeCreds(), key, file: out });
      const after = await originals.head(o.key);
      if (!before || !after || before.size !== after.size || before.etag !== after.etag || before.lastModified !== after.lastModified) {
        console.log(`X  STOP: the original ${o.key} looks different after the upload (before ${JSON.stringify(before)}, after ${JSON.stringify(after)}). Nothing more is done.`);
        process.exit(2);
      }
      const check = await originals.head(key);
      if (!r.created) { skipped++; console.log(`=  ${key} (created meanwhile, kept)`); continue; }
      if (!check || check.size !== statSync(out).size) throw new Error(`the uploaded copy cannot be read back with the read-only key (${JSON.stringify(check)})`);
      made++; console.log(`OK ${key}  ${(o.size / 1e6).toFixed(0)} MB -> ${(statSync(out).size / 1e6).toFixed(1)} MB, ${meta.frame_count} frames, ${((Date.now() - t0) / 1000).toFixed(0)} s · original unchanged (etag ${before.etag})`);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  } catch (e) { failed++; console.log(`X  ${o.key}: ${e.message}`); }
}
console.log(`done: ${made} created, ${skipped} already there, ${failed} failed`);
process.exit(failed ? 1 : 0);
