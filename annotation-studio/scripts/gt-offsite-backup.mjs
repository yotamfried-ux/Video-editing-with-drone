#!/usr/bin/env node
// Local-first independent backup of Ground Truth (database + labelled originals) to ANOTHER physical device.
//   node scripts/gt-offsite-backup.mjs run     --to E:\sportreel-gt [--scope labelled|all]
//   node scripts/gt-offsite-backup.mjs verify  --to E:\sportreel-gt   (decrypts + re-hashes everything; do this monthly)
//   node scripts/gt-offsite-backup.mjs restore --to E:\sportreel-gt   (into an EMPTY STUDIO_HOME / database: a recovery drill)
//   node scripts/gt-offsite-backup.mjs status
// Encryption is mandatory. The passphrase (>= 12 chars) is read from STUDIO_BACKUP_KEY or from --key-file <file> (a file
// readable only by you, e.g. on the operator's encrypted system disk — NEVER on the backup disk and never in Git).
// --key <passphrase> still works but puts the key in shell history; prefer the variable or the key file.
// --plaintext-device-encrypted: write the legacy unencrypted layout ONLY if the destination disk itself is fully
// encrypted (BitLocker To Go / FileVault / LUKS); the attestation is recorded in the manifest and audit log.
// Refuses a destination on the same device/physical disk as the live data. Never deletes anything in the destination.
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';
import { runOffsiteBackup, verifyOffsite, restoreFromOffsite, backupStatus } from '../server/offsite.mjs';

const [cmd, ...rest] = process.argv.slice(2);
const arg = n => { const i = rest.indexOf(n); return i >= 0 ? rest[i + 1] : undefined; };
const home = process.env.STUDIO_HOME ?? path.join(os.homedir(), '.sportreel-annotation-studio');
const to = arg('--to');
import { readFileSync } from 'node:fs';
const keyFile = arg('--key-file');
const key = arg('--key') ?? (keyFile ? readFileSync(keyFile, 'utf8').trim() : undefined) ?? process.env.STUDIO_BACKUP_KEY;
const plaintext = rest.includes('--plaintext-device-encrypted') ? 'device-encrypted' : undefined;
if (!['run', 'verify', 'restore', 'status'].includes(cmd) || (cmd !== 'status' && !to)) {
  console.error('usage: gt-offsite-backup.mjs run|verify|restore --to DIR [--scope labelled|all] [--key-file FILE | env STUDIO_BACKUP_KEY] [--plaintext-device-encrypted]  |  status');
  process.exit(2);
}
try {
  if (cmd === 'verify') {
    const r = await verifyOffsite(to, { encryption_key: key });
    console.log(JSON.stringify(r));
    process.exit(r.ok ? 0 : 1);
  }
  const ctx = createContext(home);
  if (cmd === 'status') {
    console.log(JSON.stringify(backupStatus(ctx.db)));
  } else if (cmd === 'run') {
    const r = await runOffsiteBackup(ctx, to, { scope: arg('--scope') ?? 'labelled', encryption_key: key, plaintext });
    console.log(JSON.stringify({ ok: r.ok, scope: r.scope, copied: r.copied, skipped: r.skipped, repaired: r.repaired, failed: r.failed, db_file: r.db_file, encrypted: r.encrypted, sqlite_file: r.sqlite_file, device_check: r.device_check }));
    process.exitCode = r.ok ? 0 : 1;
  } else {
    console.log(JSON.stringify(await restoreFromOffsite(ctx, to, { encryption_key: key })));
  }
  ctx.db.close?.();
} catch (e) {
  console.error(`${e.code ?? 'ERROR'}: ${e.message}`);
  process.exit(1);
}
