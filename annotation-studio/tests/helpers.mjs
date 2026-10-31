import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';
import { PgDb } from '../server/pgdb.mjs';
import { loadSql } from '../scripts/gt-migrate.mjs';

export { makeVideo } from '../scripts/synthetic.mjs';

export function tmp(prefix = 'studio-test-') { return mkdtempSync(path.join(os.tmpdir(), prefix)); }
/** Fresh isolated PostgreSQL schema per test when STUDIO_TEST_DB_URL is set (same tests, real Postgres). */
function pgUrlForFreshSchema() {
  const admin = process.env.STUDIO_TEST_DB_URL;
  const schema = `gt_t_${Math.random().toString(36).slice(2, 10)}`;
  const a = new PgDb(admin);
  for (const m of loadSql(schema).migrations) a.script(m.sql);
  a.close();
  return `${admin}${admin.includes('?') ? '&' : '?'}options=-c%20search_path%3D${schema}`;
}
export const BACKEND = process.env.STUDIO_TEST_DB_URL ? 'postgres' : 'sqlite';
export function newCtx(opts) {
  const home = tmp();
  const dbUrl = process.env.STUDIO_TEST_DB_URL ? pgUrlForFreshSchema() : undefined;
  return createContext(home, { token: 'test-token', dbUrl, ...opts });
}
export const seg = (id, s, e, o = {}) => ({ id, start_frame: s, end_frame: e, athlete_id: null, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null, ...o });
export const kf = (id, segment_id, frame, bbox, o = {}) => ({ id, segment_id, frame, bbox, visibility: 'visible', origin: 'manual', ...o });
export { writeFileSync };
