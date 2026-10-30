#!/usr/bin/env node
// Applies db/migrations/*.sql (and optionally db/roles.sql) to a PostgreSQL database. Explicit and manual:
//   STUDIO_ADMIN_DB_URL=postgres://admin@host/db node scripts/gt-migrate.mjs [--schema ground_truth] [--roles] [--dry-run]
// Refuses to run against a URL unless STUDIO_ADMIN_DB_URL is set (never reuses pipeline/Supabase env vars).
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dbDir = path.join(here, '..', 'db');

export function loadSql(schema) {
  if (!/^[a-z_][a-z0-9_]*$/.test(schema)) throw new Error('invalid schema name');
  const migrations = readdirSync(path.join(dbDir, 'migrations')).filter(f => f.endsWith('.sql')).sort()
    .map(f => ({ name: f, sql: readFileSync(path.join(dbDir, 'migrations', f), 'utf8').replaceAll('__SCHEMA__', schema) }));
  const roles = readFileSync(path.join(dbDir, 'roles.sql'), 'utf8').replaceAll('__SCHEMA__', schema);
  return { migrations, roles };
}

export async function migrate(url, { schema = 'ground_truth', roles = false, dryRun = false } = {}) {
  const { default: pg } = await import('pg');
  const { migrations, roles: rolesSql } = loadSql(schema);
  const client = new pg.Client({ connectionString: url });
  await client.connect();
  const applied = [];
  try {
    for (const m of migrations) {
      await client.query('begin');
      try {
        await client.query(m.sql);
        if (dryRun) await client.query('rollback'); else await client.query('commit');
        applied.push(m.name);
      } catch (e) { await client.query('rollback'); throw new Error(`${m.name}: ${e.message}`); }
    }
    if (roles) {
      await client.query('begin');
      try { await client.query(rolesSql); await client.query(dryRun ? 'rollback' : 'commit'); }
      catch (e) { await client.query('rollback'); throw new Error(`roles.sql: ${e.message}`); }
    }
  } finally { await client.end(); }
  return { applied, dryRun, roles };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const url = process.env.STUDIO_ADMIN_DB_URL;
  if (!url) { console.error('STUDIO_ADMIN_DB_URL is required (dedicated Ground Truth admin connection)'); process.exit(2); }
  const arg = n => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : undefined; };
  const r = await migrate(url, { schema: arg('--schema') ?? 'ground_truth', roles: process.argv.includes('--roles'), dryRun: process.argv.includes('--dry-run') });
  console.log(JSON.stringify(r));
}
