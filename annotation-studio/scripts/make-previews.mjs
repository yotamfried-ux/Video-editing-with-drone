// Creates the lightweight playback copies (720p, frame for frame) of the cloud originals, on THIS computer.
//   node --env-file=.studio-cloud.env scripts/make-previews.mjs            (all catalogued DJI originals)
//   node --env-file=.studio-cloud.env scripts/make-previews.mjs --only DJI_20260724103751_0165_D --dry-run
// Reads originals with the read-only key (STUDIO_CLOUD_R2_*). Writes ONLY new objects into the separate preview
// bucket (STUDIO_PREVIEW_R2_BUCKET + STUDIO_PREVIEW_R2_WRITE_ACCESS_KEY_ID / _SECRET_ACCESS_KEY): it never deletes,
// never overwrites an existing preview (unless --force) and refuses to write into the originals' bucket.
import os from 'node:os'; import path from 'node:path'; import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { CloudBucket, cloudConfigFromEnv, SOURCE_PREFIXES } from '../server/cloud.mjs';
import { previewKey, makePreview, putObject } from '../server/previews.mjs';
import { probeMp4, rangeReaderForCloud } from '../server/mp4probe.mjs';

const argv = process.argv.slice(2), flag = n => argv.includes(n), val = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const env = process.env, die = m => { console.error(`X  ${m}`); process.exit(1); };
const src = cloudConfigFromEnv(env); if (!src) die('STUDIO_CLOUD_R2_* is not set (use --env-file=.studio-cloud.env)');
const bucket = env.STUDIO_PREVIEW_R2_BUCKET || die('STUDIO_PREVIEW_R2_BUCKET is not set');
if (bucket === src.bucket && !flag('--allow-same-bucket')) die(`refusing to write previews into the originals' bucket "${bucket}"`);
const write = { endpoint: env.STUDIO_PREVIEW_R2_ENDPOINT || src.endpoint, bucket, accessKeyId: env.STUDIO_PREVIEW_R2_WRITE_ACCESS_KEY_ID, secretAccessKey: env.STUDIO_PREVIEW_R2_WRITE_SECRET_ACCESS_KEY };
if (!flag('--dry-run') && (!write.accessKeyId || !write.secretAccessKey)) die('STUDIO_PREVIEW_R2_WRITE_ACCESS_KEY_ID / _SECRET_ACCESS_KEY are not set (a key scoped to the preview bucket only)');
const originals = new CloudBucket(src);
const previews = new CloudBucket({ endpoint: write.endpoint, bucket, accessKeyId: env.STUDIO_PREVIEW_R2_ACCESS_KEY_ID || write.accessKeyId || src.accessKeyId, secretAccessKey: env.STUDIO_PREVIEW_R2_SECRET_ACCESS_KEY || write.secretAccessKey || src.secretAccessKey });
const include = (val('--only') ?? env.STUDIO_CLOUD_INCLUDE ?? '').trim().toLowerCase();

const all = (await Promise.all(SOURCE_PREFIXES.map(p => originals.list(p)))).flat()
  .filter(o => /\.(mp4|mov|m4v)$/i.test(o.key) && (!include || o.key.toLowerCase().includes(include)));
console.log(`${all.length} originals${include ? ` matching "${include}"` : ''}`);
let made = 0, skipped = 0, failed = 0;
for (const o of all) {
  const key = previewKey(o.key);
  try {
    if (!flag('--force') && await previews.head(key).catch(() => null)) { skipped++; console.log(`=  ${key} (exists)`); continue; }
    const meta = await probeMp4(rangeReaderForCloud(originals, o.key), o.size);
    if (flag('--dry-run')) { console.log(`?  ${o.key} -> ${key}: ${meta.width}x${meta.height} ${meta.frame_count} frames (dry run)`); continue; }
    const dir = mkdtempSync(path.join(os.tmpdir(), 'preview-')), out = path.join(dir, 'p.mp4');
    try {
      const t0 = Date.now();
      await makePreview(originals.presignGet(o.key, 6 * 3600), out, meta);
      await putObject({ ...write, key, file: out });
      made++; console.log(`OK ${key}  ${(o.size / 1e6).toFixed(0)} MB -> ${(statSync(out).size / 1e6).toFixed(1)} MB, ${meta.frame_count} frames, ${((Date.now() - t0) / 1000).toFixed(0)} s`);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  } catch (e) { failed++; console.log(`X  ${o.key}: ${e.message}`); }
}
console.log(`done: ${made} created, ${skipped} already there, ${failed} failed`);
process.exit(failed ? 1 : 0);
