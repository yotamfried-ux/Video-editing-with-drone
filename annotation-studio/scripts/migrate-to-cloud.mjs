#!/usr/bin/env node
// One-time move of THIS computer's Studio catalog into the hosted Studio (Supabase via Vercel).
//   node --env-file=.studio-cloud.env scripts/migrate-to-cloud.mjs --url https://studio.example.com --code <access code>
// Reads the local catalog (STUDIO_HOME) read-only, exports every table, and uploads it once (gzip). The hosted side
// imports only into an EMPTY database and verifies every table after the import, so existing cloud data is never
// overwritten and a partial import is never left behind. The local Studio and its files are not changed.
import { gzipSync } from 'node:zlib';
import { createContext } from '../server/context.mjs';
import { exportBackup } from '../server/backup.mjs';

const arg = n => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : undefined; };
const url = (arg('--url') ?? '').replace(/\/+$/, ''), code = arg('--code') ?? process.env.STUDIO_CLOUD_CODE;
if (!/^https:\/\//.test(url) || !code) { console.error('usage: migrate-to-cloud.mjs --url https://<hosted studio> --code <access code>'); process.exit(2); }
const home = process.env.STUDIO_HOME;
if (!home) { console.error('STUDIO_HOME is not set (run with --env-file=.studio-cloud.env)'); process.exit(2); }

const ctx = createContext(home, { dbUrl: '' });          // the LOCAL SQLite catalog, never a remote database
const backup = exportBackup(ctx.db);
const body = gzipSync(Buffer.from(JSON.stringify(backup)));
const counts = Object.entries(backup.counts).filter(([, n]) => n).map(([t, n]) => `${t}=${n}`).join(', ');
console.log(`local catalog: ${counts || 'empty'}`);
console.log(`upload size: ${(body.length / 1e6).toFixed(2)} MB (gzip)`);
if (body.length > 4.2e6) { console.error('The export is larger than the hosted request limit (about 4.5 MB). Tell Claude the sizes above; the import can be split.'); process.exit(1); }

const r = await fetch(`${url}/api/admin/import-backup`, {
  method: 'POST', body, headers: { authorization: `Bearer ${code}`, 'content-type': 'application/json', 'content-encoding': 'gzip', origin: url },
});
const j = await r.json().catch(() => ({}));
if (!r.ok) { console.error(`FAILED (${r.status}): ${j.detail ?? j.message ?? JSON.stringify(j)}`); process.exit(1); }
console.log(`OK — imported and verified: ${Object.entries(j.restored ?? {}).filter(([, n]) => n).map(([t, n]) => `${t}=${n}`).join(', ')}`);
console.log(`digest ${j.digest}`);
