import path from 'node:path';
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { openDb } from './db.mjs';
import { LocalArchive } from './archive.mjs';
import { CloudBucket, cloudConfigFromEnv } from './cloud.mjs';

/** Build the runtime context from a home directory (state is entirely under it). */
export function createContext(home, { roots = [], token, dbUrl, archive, cloud } = {}) {
  mkdirSync(home, { recursive: true });
  const tokenFile = path.join(home, 'token');
  let t = token ?? process.env.STUDIO_TOKEN;
  if (!t) {
    if (existsSync(tokenFile)) t = readFileSync(tokenFile, 'utf8').trim();
    else { t = randomBytes(24).toString('hex'); writeFileSync(tokenFile, t, { mode: 0o600 }); }
  }
  return {
    home, token: t, roots, dbUrl: dbUrl ?? process.env.STUDIO_DB_URL,
    db: openDb(home, { url: dbUrl ?? process.env.STUDIO_DB_URL }),
    archive: archive ?? new LocalArchive(path.join(home, 'archive')),
    // Optional read-only view of SportReel's existing source videos in R2 (STUDIO_CLOUD_R2_*); null when not configured.
    cloud: cloud ?? (() => { const c = cloudConfigFromEnv(); return c ? new CloudBucket(c) : null; })(),
    cloudMetadata: process.env.STUDIO_CLOUD_METADATA || null,
    cacheDir: path.join(home, 'cache'),
    outputsDir: path.join(home, 'outputs'),
  };
}
