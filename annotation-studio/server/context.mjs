import path from 'node:path';
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { openDb } from './db.mjs';
import { LocalArchive } from './archive.mjs';
import { CloudBucket, cloudConfigFromEnv } from './cloud.mjs';
import { previewLookup } from './previews.mjs';

/** Build the runtime context from a home directory (state is entirely under it). */
export function createContext(home, { roots = [], token, dbUrl, archive, cloud } = {}) {
  mkdirSync(home, { recursive: true });
  const tokenFile = path.join(home, 'token');
  let t = token ?? process.env.STUDIO_TOKEN;
  if (!t) {
    if (existsSync(tokenFile)) t = readFileSync(tokenFile, 'utf8').trim();
    else { t = randomBytes(24).toString('hex'); writeFileSync(tokenFile, t, { mode: 0o600 }); }
  }
  const ctx = {
    home, token: t, roots, dbUrl: dbUrl ?? process.env.STUDIO_DB_URL,
    db: openDb(home, { url: dbUrl ?? process.env.STUDIO_DB_URL }),
    archive: archive ?? new LocalArchive(path.join(home, 'archive')),
    // Optional read-only view of SportReel's existing source videos in R2 (STUDIO_CLOUD_R2_*); null when not configured.
    cloud: cloud ?? (() => { const c = cloudConfigFromEnv(); return c ? new CloudBucket(c) : null; })(),
    cloudMetadata: process.env.STUDIO_CLOUD_METADATA || null,
    // Optional catalog filter: list only objects whose key or name contains this text (e.g. DJI for drone footage). Empty = all.
    cloudInclude: (process.env.STUDIO_CLOUD_INCLUDE ?? '').trim(),
    // Hosted mode (Vercel): no long-lived process, no local disk worth keeping; originals play straight from R2.
    serverless: !!process.env.VERCEL || process.env.STUDIO_SERVERLESS === '1',
    // Host names (besides localhost) this server answers to, e.g. studio.d2ryf.com and the project's *.vercel.app names.
    allowedHosts: [process.env.STUDIO_ALLOWED_HOSTS, process.env.VERCEL_URL, process.env.VERCEL_BRANCH_URL, process.env.VERCEL_PROJECT_PRODUCTION_URL]
      .filter(Boolean).join(',').split(',').map(h => h.trim().toLowerCase()).filter(h => /^[a-z0-9.-]+$/.test(h)),
    cacheDir: path.join(home, 'cache'),
    outputsDir: path.join(home, 'outputs'),
  };
  // Light 720p playback copies: studio/previews/ in the SAME bucket, read with the same read-only key. Playback uses
  // a copy when it exists and the original otherwise. STUDIO_CLOUD_PREVIEWS=0 turns this off.
  ctx.previews = ctx.cloud && process.env.STUDIO_CLOUD_PREVIEWS !== '0' ? { bucket: ctx.cloud, find: previewLookup(ctx.cloud) } : null;
  return ctx;
}
