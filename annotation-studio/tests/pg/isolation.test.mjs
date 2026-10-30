// Authorization-denial and isolation proof on REAL PostgreSQL (skipped unless STUDIO_TEST_DB_URL is set).
// Simulates Supabase's production roles (anon / authenticated / service_role[BYPASSRLS]) and shows the pipeline side
// cannot read or write Ground Truth, that the Studio role cannot delete or rewrite history, and that the evaluator
// role sees frozen data only.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { migrate } from '../../scripts/gt-migrate.mjs';
import { createContext } from '../../server/context.mjs';
import { reconcile } from '../../server/ingest.mjs';
import * as A from '../../server/annotations.mjs';
import * as D from '../../server/datasets.mjs';
import * as E from '../../server/evaluate.mjs';
import { makeVideo, tmp, seg } from '../helpers.mjs';

const ADMIN = process.env.STUDIO_TEST_DB_URL;
const skip = !ADMIN;
const require = createRequire(import.meta.url);

// Throwaway test-database roles get throwaway passwords so the same tests work with trust auth (local) and scram (CI service container).
const withDb = u => name => { const x = new URL(u); x.pathname = `/${name}`; return x.toString(); };
const asRole = (admin, db, role) => { const x = new URL(withDb(admin)(db)); x.username = role; x.password = `pw_${role}`; return x.toString(); };
const denied = async (pool, sql, params = []) => { try { await pool.query(sql, params); } catch (e) { return e.code; } return 'allowed'; };

async function setup() {
  const { default: pg } = await import('pg');
  const db = `gt_iso_${Math.random().toString(36).slice(2, 8)}`;
  const admin = new pg.Client({ connectionString: ADMIN }); await admin.connect();
  await admin.query(`create database ${db}`);
  const a = new pg.Client({ connectionString: withDb(ADMIN)(db) }); await a.connect();
  // stand-ins for Supabase platform roles + a production-like public table they can use
  for (const r of ['anon', 'authenticated']) await a.query(`do $$ begin if not exists (select 1 from pg_roles where rolname='${r}') then create role ${r} nologin; end if; end $$`);
  await a.query(`do $$ begin if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role login bypassrls; end if; end $$`);
  await a.query(`alter role anon login; alter role authenticated login;`);
  await a.query(`create table public.reels(id int primary key); grant all on public.reels to anon, authenticated, service_role`);
  await a.query(`do $$ begin if not exists (select 1 from pg_roles where rolname='gt_studio') then create role gt_studio login; end if; if not exists (select 1 from pg_roles where rolname='gt_evaluator') then create role gt_evaluator login; end if; end $$`);
  for (const r of ['gt_studio', 'gt_evaluator', 'anon', 'authenticated', 'service_role']) await a.query(`alter role ${r} password 'pw_${r}'`);
  const cleanup = async () => { await a.end().catch(() => {}); await admin.query(`drop database if exists ${db} with (force)`).catch(() => {}); await admin.end().catch(() => {}); };
  try { await migrate(withDb(ADMIN)(db), { schema: 'ground_truth', roles: true }); } catch (e) { await cleanup(); throw e; }
  const mk = role => new pg.Pool({ connectionString: asRole(ADMIN, db, role), max: 1 });
  return { pg, db, admin, a, mk, cleanup };
}

test('pipeline-side roles (anon, authenticated, service_role) cannot touch Ground Truth', { skip }, async () => {
  const w = await setup();
  try {
    const bypass = (await w.a.query("select rolbypassrls from pg_roles where rolname='service_role'")).rows[0].rolbypassrls;
    assert.equal(bypass, true, 'service_role bypasses RLS, so only privileges can protect GT (this is what we test)');
    for (const role of ['anon', 'authenticated', 'service_role']) {
      const pool = w.mk(role);
      assert.equal(await denied(pool, 'select 1 from public.reels'), 'allowed', `${role} keeps normal production access`);
      for (const t of ['sources', 'annotation_drafts', 'annotation_revisions', 'athletes', 'dataset_versions', 'frozen_revisions', 'audit_log']) {
        assert.equal(await denied(pool, `select * from ground_truth.${t}`), '42501', `${role} must not read ${t}`);
      }
      assert.equal(await denied(pool, `insert into ground_truth.audit_log(at,actor,action) values ('x','y','z')`), '42501');
      assert.equal(await denied(pool, `delete from ground_truth.sources`), '42501');
      assert.equal(await denied(pool, `create table ground_truth.x(a int)`), '42501');
      assert.equal(await denied(pool, `select ground_truth.reject_append_only()`), '42501');
      const priv = (await w.a.query(`select has_schema_privilege('${role}','ground_truth','USAGE') u,
        (select count(*) from information_schema.table_privileges where grantee='${role}' and table_schema='ground_truth') g`)).rows[0];
      assert.equal(priv.u, false); assert.equal(Number(priv.g), 0);
      await pool.end();
    }
  } finally { await w.cleanup(); }
});

test('Studio role: working access, but no deletes, no history rewrites, no DDL, no production tables', { skip }, async () => {
  const w = await setup();
  try {
    const s = w.mk('gt_studio');
    const now = new Date().toISOString();
    assert.equal(await denied(s, `insert into athletes(id,label,created_at) values('a1','x',$1)`, [now]), 'allowed');
    assert.equal(await denied(s, `delete from athletes`), '42501', 'no delete privilege on any table');
    assert.equal(await denied(s, `truncate ground_truth.athletes`), '42501');
    assert.equal(await denied(s, `update annotation_revisions set reason='x'`), '42501', 'append-only tables are not even updatable by the Studio role');
    assert.equal(await denied(s, `drop table ground_truth.athletes`), '42501');
    assert.equal(await denied(s, `create table ground_truth.evil(a int)`), '42501');
    assert.equal(await denied(s, `select * from public.reels`), '42501', 'Studio role cannot read production tables');
    assert.equal(await denied(s, `alter role gt_studio superuser`), '42501');
    await s.end();
    // even the owner cannot rewrite history: DB triggers
    await w.a.query(`insert into ground_truth.sources(id,sha256,byte_size,display_name,created_at) values ('s1','${'a'.repeat(64)}',1,'n','t')`);
    await w.a.query(`insert into ground_truth.annotation_revisions(id,source_id,seq,content,digest,author,schema_version,scope,created_at,approved_at)
      values ('r1','s1',1,'{}','d','op',1,'source','t','t')`);
    await w.a.query('set role gt_owner');
    for (const sql of [`update ground_truth.annotation_revisions set content='{"x":1}'`, `delete from ground_truth.annotation_revisions`,
      `update ground_truth.sources set sha256='${'b'.repeat(64)}'`, `delete from ground_truth.sources`]) {
      await assert.rejects(w.a.query(sql), /IMMUTABLE|PROTECTED/, sql);
    }
    await w.a.query('reset role');
  } finally { await w.cleanup(); }
});

test('end-to-end on Postgres roles: Studio ingests+annotates+freezes; evaluator reads frozen data only', { skip, timeout: 120000 }, async () => {
  const w = await setup();
  const raw = path.join(tmp('ops-'), 'raw');
  const open = [];
  try {
    makeVideo(path.join(raw, 'a.mp4'), { seconds: 2, tag: 'iso' });
    const studio = createContext(tmp(), { token: 't', dbUrl: asRole(ADMIN, w.db, 'gt_studio') }); open.push(studio);
    await reconcile(studio, { roots: [{ dir: raw, prefix: 'raw/' }] });
    const src = studio.db.prepare('select * from sources').get();
    const ath = A.createAthlete(studio.db, 'S1');
    const c = A.emptyContent(); c.segments.push(seg('s', 5, 40, { athlete_id: ath.id })); c.reviewed_ranges.push({ start_frame: 0, end_frame: 60 });
    A.saveDraft(studio.db, src.id, 0, c);
    A.approve(studio.db, src.id, { expectedVersion: 1 });
    const ds = D.freezeDataset(studio.db, { name: 'v1', sourceIds: [src.id], policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
    const pred = E.importPredictions(studio.db, { run_id: 'r1', pipeline_version: 'abc', sources: [{ source_sha256: src.sha256, events: [{ start_frame: 6, end_frame: 39, athlete_key: 'k' }] }] });
    // Studio role cannot delete/rewrite through the application either
    assert.throws(() => studio.db.prepare('delete from annotation_revisions').run(), /permission denied/);
    assert.throws(() => studio.db.prepare("update annotation_revisions set reason='x'").run(), /permission denied/);

    const ev = createContext(tmp(), { token: 't', dbUrl: asRole(ADMIN, w.db, 'gt_evaluator') }); open.push(ev);
    const out = E.runEvaluation(ev.db, { dataset_id: ds.id, prediction_id: pred.id });
    assert.equal(out.report.metrics.event_recall, 1);
    for (const t of ['sources', 'annotation_drafts', 'athletes', 'athlete_appearances', 'upload_batches', 'source_locations', 'edl_records', 'dataset_members']) {
      assert.throws(() => ev.db.prepare(`select * from ${t}`).all(), /permission denied/, `evaluator must not read ${t}`);
    }
    assert.throws(() => ev.db.prepare("update evaluation_runs set report='{}'").run(), /permission denied/);
    assert.ok(ev.db.prepare('select count(*) n from frozen_revisions').get().n >= 1);
    // result is visible to the Studio and immutable
    assert.equal(studio.db.prepare('select count(*) n from evaluation_runs').get().n, 1);
  } finally { for (const c of open) c.db.close(); await w.cleanup(); }
});

test('migrations are idempotent, versioned, and a dry run changes nothing', { skip }, async () => {
  const w = await setup();
  try {
    await migrate(withDb(ADMIN)(w.db), { schema: 'ground_truth', roles: true });  // second apply
    const v = (await w.a.query('select version from ground_truth.schema_migrations')).rows.map(r => r.version);
    assert.deepEqual(v, ['0001_ground_truth']);
    const r = await migrate(withDb(ADMIN)(w.db), { schema: 'gt_dry', dryRun: true });
    assert.equal(r.dryRun, true);
    assert.equal((await w.a.query("select count(*) n from information_schema.schemata where schema_name='gt_dry'")).rows[0].n, '0');
  } finally { await w.cleanup(); }
});
void require;
