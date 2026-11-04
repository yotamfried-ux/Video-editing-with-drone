// Lightweight playback copies ("previews") of the cloud originals.
// The DJI originals are 4K/59.94 at ~100-170 Mb/s: too heavy to stream for marking. A preview is the same video,
// FRAME FOR FRAME (same frame count and timestamps: annotations use frame numbers and normalised boxes, so they apply
// unchanged), scaled to 720p H.264 (~3-6 Mb/s) with a keyframe every 0.5 s for fast seeking.
// Previews live in their OWN bucket (never the pipeline's bucket); the Studio only reads them.
import { spawn } from 'node:child_process';
import { readFileSync, statSync, openSync, readSync, closeSync } from 'node:fs';
import { CloudBucket, CloudError } from './cloud.mjs';
import { signRequest, sha256hex } from './sigv4.mjs';
import { probeMp4 } from './mp4probe.mjs';

/** processed/2026-..._DJI_0165_D.MP4 -> processed/2026-..._DJI_0165_D.preview.mp4 */
export const previewKey = originalKey => `${originalKey.replace(/\.[^./]+$/, '')}.preview.mp4`;

/** Read side (Studio): STUDIO_PREVIEW_R2_BUCKET, credentials default to the Studio's read-only cloud token. */
export function previewBucketFromEnv(env = process.env) {
  if (!env.STUDIO_PREVIEW_R2_BUCKET) return null;
  const pick = n => env[`STUDIO_PREVIEW_R2_${n}`] || env[`STUDIO_CLOUD_R2_${n}`];
  const account = pick('ACCOUNT_ID'), endpoint = env.STUDIO_PREVIEW_R2_ENDPOINT || env.STUDIO_CLOUD_R2_ENDPOINT || (account && `https://${account}.r2.cloudflarestorage.com`);
  if (!endpoint || !pick('ACCESS_KEY_ID') || !pick('SECRET_ACCESS_KEY')) throw new CloudError('CLOUD_CONFIG', 'STUDIO_PREVIEW_R2_BUCKET needs an account id and credentials');
  return new CloudBucket({ endpoint, bucket: env.STUDIO_PREVIEW_R2_BUCKET, accessKeyId: pick('ACCESS_KEY_ID'), secretAccessKey: pick('SECRET_ACCESS_KEY') });
}

/** Cached existence check (a HEAD per playback would add latency). */
export function previewLookup(bucket, { ttlMs = 10 * 60 * 1000 } = {}) {
  const cache = new Map();
  return async originalKey => {
    const k = previewKey(originalKey), hit = cache.get(k);
    if (hit && Date.now() - hit.at < (hit.ok ? ttlMs : 60000)) return hit.ok ? k : null;
    let ok = false; try { ok = !!(await bucket.head(k)); } catch { ok = false; }
    cache.set(k, { ok, at: Date.now() }); return ok ? k : null;
  };
}

const run = (cmd, args) => new Promise((res, rej) => {
  const p = spawn(cmd, args, { stdio: ['ignore', 'ignore', 'pipe'] }); let err = '';
  p.stderr.on('data', d => { err += d; if (err.length > 8000) err = err.slice(-8000); });
  p.on('error', rej); p.on('close', c => (c === 0 ? res() : rej(new Error(`${cmd} exited ${c}: ${err.trim().split('\n').slice(-3).join(' | ')}`))));
});
const fileReader = file => async (start, end) => {
  const fd = openSync(file, 'r'); try { const b = Buffer.alloc(end - start + 1); readSync(fd, b, 0, b.length, start); return b; } finally { closeSync(fd); }
};
export const probeFile = file => probeMp4(fileReader(file), statSync(file).size);

/** Transcode to the preview and PROVE it is frame-for-frame: same frame count, same frame rate. */
export async function makePreview(input, dest, expect, { height = 720, crf = 24 } = {}) {
  const gop = Math.max(1, Math.round(expect.fps_num / expect.fps_den / 2));
  await run(process.env.STUDIO_FFMPEG || 'ffmpeg', ['-y', '-v', 'error', '-i', input, '-map', '0:v:0', '-an', '-sn', '-dn',
    '-vf', `scale=-2:${height}`, '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', String(crf),
    '-pix_fmt', 'yuv420p', '-g', String(gop), '-keyint_min', String(gop), '-sc_threshold', '0', '-movflags', '+faststart', dest]);
  const got = await probeFile(dest);
  if (got.frame_count !== expect.frame_count || got.fps_num * expect.fps_den !== expect.fps_num * got.fps_den) {
    throw new Error(`preview is not frame-for-frame: ${got.frame_count} frames @ ${got.fps_num}/${got.fps_den} vs ${expect.frame_count} @ ${expect.fps_num}/${expect.fps_den}`);
  }
  return got;
}

/** Write side (operator's computer only): a single signed PUT of a new object into the PREVIEW bucket. */
export async function putObject({ endpoint, bucket, accessKeyId, secretAccessKey, key, file, contentType = 'video/mp4', fetchImpl = fetch }) {
  const body = readFileSync(file);
  const url = `${endpoint.replace(/\/+$/, '')}/${bucket}/${key.split('/').map(encodeURIComponent).join('/')}`;
  const { _canonical, ...headers } = signRequest({ method: 'PUT', url, headers: { 'content-type': contentType }, payloadHash: sha256hex(body), region: 'auto', service: 's3', accessKeyId, secretAccessKey });
  const r = await fetchImpl(url, { method: 'PUT', headers, body });
  if (r.status !== 200) throw new Error(`upload of ${key} returned ${r.status}`);
}
