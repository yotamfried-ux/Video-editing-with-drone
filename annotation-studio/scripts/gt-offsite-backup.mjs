#!/usr/bin/env node
// Local-first independent backup of Ground Truth (database + labelled originals) to ANOTHER physical device.
//   node scripts/gt-offsite-backup.mjs run    --to /Volumes/Backup/sportreel-gt [--scope labelled|all]
//   node scripts/gt-offsite-backup.mjs verify --to /Volumes/Backup/sportreel-gt        (re-hashes everything; do this monthly)
//   node scripts/gt-offsite-backup.mjs restore --to /Volumes/Backup/sportreel-gt        (into an EMPTY STUDIO_HOME / database: a recovery drill)
// Refuses a destination on the same device as the live data. Never deletes anything in the destination.
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';
import { runOffsiteBackup, verifyOffsite, restoreFromOffsite, backupStatus } from '../server/offsite.mjs';

const [cmd, ...rest] = process.argv.slice(2);
const arg = n => { const i = rest.indexOf(n); return i >= 0 ? rest[i + 1] : undefined; };
const home = process.env.STUDIO_HOME ?? path.join(os.homedir(), '.sportreel-annotation-studio');
const to = arg('--to');
if (!['run', 'verify', 'restore', 'status'].includes(cmd) || (cmd !== 'status' && !to)) { console.error('usage: gt-offsite-backup.mjs run|verify|restore --to DIR [--scope labelled|all]  |  status'); process.exit(2); }
try {
  if (cmd === 'verify') { const r = await verifyOffsite(to); console.log(JSON.stringify(r)); process.exit(r.ok ? 0 : 1); }
  const ctx = createContext(home);
  if (cmd === 'status') console.log(JSON.stringify(backupStatus(ctx.db)));
  else if (cmd === 'run') { const r = await runOffsiteBackup(ctx, to, { scope: arg('--scope') ?? 'labelled' }); console.log(JSON.stringify({ ok: r.ok, scope: r.scope, copied: r.copied, skipped: r.skipped, repaired: r.repaired, failed: r.failed, db_file: r.db_file })); process.exitCode = r.ok ? 0 : 1; }
  else console.log(JSON.stringify(await restoreFromOffsite(ctx, to)));
  ctx.db.close?.();
} catch (e) { console.error(`${e.code ?? 'ERROR'}: ${e.message}`); process.exit(1); }
