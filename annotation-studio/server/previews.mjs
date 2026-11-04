// Lightweight playback copies ("previews") of the cloud originals.
// The DJI originals are 4K/59.94 at ~100-170 Mb/s: too heavy to stream for marking. A preview is the same video,
// FRAME FOR FRAME (same frame count and rate: annotations use frame numbers and normalised boxes, so they apply
// unchanged), scaled to 720p H.264 (~3-6 Mb/s) with a keyframe every 0.5 s for fast seeking.
//
// Storage (operator decision): the EXISTING bucket, under studio/previews/ only. Isolation is enforced by R2 itself,
// not just by this code: uploads use a short-lived R2 temporary credential, signed locally from a parent key, whose
// JWT allows exactly one operation (PutObject) under exactly one prefix (studio/previews/). With it, R2 refuses any
// read, overwrite or delete of an original. Every upload is also create-once (If-None-Match: *), so an existing
// preview is never overwritten. The Studio itself only reads.
import { spawn } from 'node:child_process';
import { readFileSync, statSync, openSync, readSync, closeSync } from 'node:fs';
import { createHmac } from 'node:crypto';
import { signRequest, sha256hex } from './sigv4.mjs';
import { probeMp4 } from './mp4probe.mjs';

export const PREVIEW_PREFIX = 'studio/previews/';
/** processed/2026-..._DJI_0165_D.MP4 -> studio/previews/processed/2026-..._DJI_0165_D.mp4 */
export const previewKey = originalKey => `${PREVIEW_PREFIX}${originalKey.replace(/\.[^./]+$/, '')}.mp4`;
export const isPreviewKey = key => typeof key === 'string' && key.startsWith(PREVIEW_PREFIX) && !key.includes('..');

/** Cached existence check through the Studio's read-only bucket client (a HEAD per playback would add latency). */
export function previewLookup(bucket, { ttlMs = 10 * 60 * 1000 } = {}) {
  const cache = new Map();
  return async originalKey => {
    const k = previewKey(originalKey), hit = cache.get(k);
    if (hit && Date.now() - hit.at < (hit.ok ? ttlMs : 60000)) return hit.ok ? k : null;
    let ok = false; try { ok = !!(await bucket.head(k)); } catch { ok = false; }
    cache.set(k, { ok, at: Date.now() }); return ok ? k : null;
  };
}

const b64u = x => Buffer.from(typeof x === 'string' ? x : JSON.stringify(x)).toString('base64url');
/**
 * R2 temporary credential, signed locally (Cloudflare "local signing"): HS256 JWT signed with the parent secret,
 * iss = parent access key id, sub = account id, aud = endpoint host. The temporary secret is sha256(jwt); the session
 * token is base64("jwt/" + jwt) and travels as X-Amz-Security-Token. It can never exceed the parent's permissions.
 */
export function r2TempCredentials({ endpoint, accountId, parentAccessKeyId, parentSecretAccessKey, bucket, actions, prefixPaths = [], objectPaths = [], ttlSeconds = 3600, now = Date.now() }) {
  if (!actions?.length) throw new Error('a temporary credential needs an explicit list of actions');
  const iat = Math.floor(now / 1000);
  const claims = { bucket, actions, paths: { prefixPaths, objectPaths }, sub: accountId, iss: parentAccessKeyId, aud: new URL(endpoint).host, iat, exp: iat + ttlSeconds };
  const head = b64u({ alg: 'HS256', typ: 'JWT' }), body = b64u(claims);
  const jwt = `${head}.${body}.${createHmac('sha256', parentSecretAccessKey).update(`${head}.${body}`).digest('base64url')}`;
  return { accessKeyId: parentAccessKeyId, secretAccessKey: sha256hex(jwt), sessionToken: Buffer.from(`jwt/${jwt}`).toString('base64'), expiresAt: claims.exp * 1000 };
}
/** The only credential the preview uploader ever uses: PutObject under studio/previews/, nothing else. */
export const previewWriteCredentials = (o) => r2TempCredentials({ ...o, actions: ['PutObject'], prefixPaths: [PREVIEW_PREFIX] });

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

/**
 * Create-once upload of one preview. Refuses (before any request) keys outside studio/previews/; sends
 * If-None-Match: * so R2 itself refuses to replace an existing object (412 -> { created: false }).
 */
export async function putPreview({ endpoint, bucket, creds, key, file, fetchImpl = fetch }) {
  if (!isPreviewKey(key)) throw new Error(`refusing to write outside ${PREVIEW_PREFIX}: ${key}`);
  const body = readFileSync(file);
  const url = `${endpoint.replace(/\/+$/, '')}/${bucket}/${key.split('/').map(encodeURIComponent).join('/')}`;
  const extra = { 'content-type': 'video/mp4', 'if-none-match': '*', ...(creds.sessionToken ? { 'x-amz-security-token': creds.sessionToken } : {}) };
  const { _canonical, ...headers } = signRequest({ method: 'PUT', url, headers: extra, payloadHash: sha256hex(body), region: 'auto', service: 's3', accessKeyId: creds.accessKeyId, secretAccessKey: creds.secretAccessKey });
  const r = await fetchImpl(url, { method: 'PUT', headers, body });
  if (r.status === 412) return { created: false };
  if (r.status !== 200) throw new Error(`upload of ${key} returned ${r.status}: ${(await r.text().catch(() => '')).slice(0, 200)}`);
  return { created: true };
}
