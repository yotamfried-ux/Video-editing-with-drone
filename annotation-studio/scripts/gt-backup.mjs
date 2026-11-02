#!/usr/bin/env node
// gt-backup.mjs export FILE | verify FILE | restore FILE | audit        (uses STUDIO_HOME / STUDIO_DB_URL like the server)
import { readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';
import { exportBackup, restoreBackup, verifyBackupFile, verifyIntegrity } from '../server/backup.mjs';

const [cmd, file] = process.argv.slice(2);
const home = process.env.STUDIO_HOME ?? path.join(os.homedir(), '.sportreel-annotation-studio');
if (cmd === 'verify') { const p = verifyBackupFile(JSON.parse(readFileSync(file, 'utf8'))); console.log(JSON.stringify({ ok: !p.length, problems: p })); process.exit(p.length ? 1 : 0); }
const ctx = createContext(home);
if (cmd === 'export') { const b = exportBackup(ctx.db); writeFileSync(file, JSON.stringify(b)); console.log(JSON.stringify({ file, digest: b.digest, counts: b.counts })); }
else if (cmd === 'restore') console.log(JSON.stringify(restoreBackup(ctx.db, JSON.parse(readFileSync(file, 'utf8')))));
else if (cmd === 'audit') { const r = verifyIntegrity(ctx.db); console.log(JSON.stringify(r)); process.exit(r.ok ? 0 : 1); }
else { console.error('usage: gt-backup.mjs export|verify|restore FILE | audit'); process.exit(2); }
ctx.db.close?.();
