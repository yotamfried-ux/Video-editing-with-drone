// Authorization-denial and isolation proof on REAL PostgreSQL (skipped unless STUDIO_TEST_DB_URL is set).
// Simulates Supabase's production roles (anon / authenticated / service_role[BYPASSRLS]) and shows the pipeline side
// cannot read or write Ground Truth, that the Studio role cannot delete or rewrite history, and that the evaluator
// role sees frozen data only.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
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
    // even an administrator cannot rewrite history: DB triggers fire for every role, including superusers
    await w.a.query(`insert into ground_truth.sources(id,sha256,byte_size,display_name,created_at) values ('s1','${'a'.repeat(64)}',1,'n','t')`);
    await w.a.query(`insert into ground_truth.annotation_revisions(id,source_id,seq,content,digest,author,schema_version,scope,created_at,approved_at)
      values ('r1','s1',1,'{}','d','op',1,'source','t','t')`);
    for (const sql of [`update ground_truth.annotation_revisions set content='{"x":1}'`, `delete from ground_truth.annotation_revisions`,
      `update ground_truth.sources set sha256='${'b'.repeat(64)}'`, `delete from ground_truth.sources`]) {
      await assert.rejects(w.a.query(sql), /IMMUTABLE|PROTECTED/, sql);
    }
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


// ---------------------------------------------------------------------------------------------------------------------
// Supabase-faithful replay. The role attributes, memberships and default privileges below were read (catalog SELECTs only,
// no data, no DDL) from the live production project on 2026-10-30 and replayed here, so the migration is applied exactly as
// it would be there: by a NON-superuser `postgres`-like role that has CREATEROLE, BYPASSRLS and membership in pg_read_all_data.
//   postgres: member of anon, authenticated, authenticator, service_role, pg_read_all_data; no global default ACLs;
//   default ACLs only for specific schemas (public, storage, ...), never <ALL SCHEMAS>.
// ---------------------------------------------------------------------------------------------------------------------
async function setupSupabaseLike() {
  const { default: pg } = await import('pg');
  const db = `gt_sb_${Math.random().toString(36).slice(2, 8)}`;
  const admin = new pg.Client({ connectionString: ADMIN }); await admin.connect();
  for (const sql of [
    `do $$ begin if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if; end $$`,
    `do $$ begin if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if; end $$`,
    `do $$ begin if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if; end $$`,
    `do $$ begin if not exists (select 1 from pg_roles where rolname='authenticator') then create role authenticator login noinherit; end if; end $$`,
    `grant anon, authenticated, service_role to authenticator`,
    `do $$ begin if not exists (select 1 from pg_roles where rolname='sb_postgres') then create role sb_postgres login createrole createdb bypassrls; end if; end $$`,
    `grant anon, authenticated, authenticator, service_role, pg_read_all_data to sb_postgres`,
    `alter role sb_postgres password 'pw_sb_postgres'`,
  ]) await admin.query(sql);
  // On the real project gt_* roles do not pre-exist and are created BY the migration role. Roles are cluster-wide, so remove any
  // left behind by the superuser-created fixtures of the other tests; otherwise the non-superuser rightly cannot administer them.
  await admin.query('drop role if exists gt_studio'); await admin.query('drop role if exists gt_evaluator');
  await admin.query(`create database ${db} owner sb_postgres`);
  const a = new pg.Client({ connectionString: withDb(ADMIN)(db) }); await a.connect();
  for (const sql of [   // the live public-schema defaults
    `grant usage on schema public to anon, authenticated, service_role`,
    `alter default privileges for role sb_postgres in schema public grant all on tables to anon, authenticated, service_role`,
    `alter default privileges for role sb_postgres in schema public grant all on sequences to anon, authenticated, service_role`,
    `alter default privileges for role sb_postgres in schema public grant execute on functions to anon, authenticated, service_role`,
  ]) await a.query(sql);
  const cleanup = async () => { await a.end().catch(() => {}); await admin.query(`drop database if exists ${db} with (force)`).catch(() => {}); await admin.end().catch(() => {}); };
  const asPostgres = () => { const x = new URL(withDb(ADMIN)(db)); x.username = 'sb_postgres'; x.password = 'pw_sb_postgres'; return x.toString(); };
  try { await migrate(asPostgres(), { schema: 'ground_truth', roles: true }); } catch (e) { await cleanup(); throw e; }
  return { db, a, cleanup, asPostgres };
}
const asRoleSql = async (client, roles, sql) => {      // run `sql` after SET ROLE chain; always RESET afterwards
  try { for (const r of roles) await client.query(`set role ${r}`); await client.query(sql); return 'allowed'; }
  catch (e) { return e.code; } finally { await client.query('reset role').catch(() => {}); }
};

test('Supabase-faithful: migration runs as a NON-superuser postgres; pipeline-side roles are denied (schema, tables, views, functions, sequences)', { skip }, async () => {
  const w = await setupSupabaseLike();
  try {
    assert.equal((await w.a.query("select rolsuper from pg_roles where rolname='sb_postgres'")).rows[0].rolsuper, false, 'migration role is not a superuser, as on Supabase');
    const owners = (await w.a.query("select distinct pg_get_userbyid(c.relowner) o from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='ground_truth' and c.relkind in ('r','v')")).rows.map(r => r.o);
    assert.deepEqual(owners, ['sb_postgres'], 'objects are owned by the migration role (no extra owner role)');
    const chains = { anon: ['anon'], authenticated: ['authenticated'], service_role: ['service_role'], 'authenticator -> service_role': ['authenticator', 'service_role'], 'authenticator -> anon': ['authenticator', 'anon'] };
    for (const [name, chain] of Object.entries(chains)) {
      assert.equal(await asRoleSql(w.a, chain, 'select count(*) from public.nonexistent_probe_ignored_fallback').then(c => c === '42P01' || c === 'allowed'), true);   // sanity: role switch works
      for (const t of ['sources', 'annotation_drafts', 'annotation_revisions', 'athletes', 'audit_log', 'frozen_revisions', 'frozen_datasets', 'meta', 'schema_migrations']) {
        assert.equal(await asRoleSql(w.a, chain, `select * from ground_truth.${t}`), '42501', `${name} must not read ${t}`);
      }
      assert.equal(await asRoleSql(w.a, chain, `insert into ground_truth.audit_log(at,actor,action) values ('x','y','z')`), '42501', name);
      assert.equal(await asRoleSql(w.a, chain, `delete from ground_truth.sources`), '42501', name);
      assert.equal(await asRoleSql(w.a, chain, `create table ground_truth.evil(a int)`), '42501', name);
      assert.equal(await asRoleSql(w.a, chain, `select ground_truth.reject_append_only()`), '42501', `${name} cannot execute GT functions`);
      assert.equal(await asRoleSql(w.a, chain, `select nextval(pg_get_serial_sequence('ground_truth.audit_log','id'))`), '42501', `${name} cannot use GT sequences`);
      const p = (await w.a.query(`select has_schema_privilege('${chain.at(-1)}','ground_truth','USAGE') u, has_schema_privilege('${chain.at(-1)}','ground_truth','CREATE') c`)).rows[0];
      assert.deepEqual([p.u, p.c], [false, false], `${name}: no schema USAGE/CREATE`);
    }
    const leaks = (await w.a.query(`select grantee, table_name, privilege_type from information_schema.table_privileges
      where table_schema='ground_truth' and grantee in ('anon','authenticated','service_role','authenticator','PUBLIC')`)).rows;
    assert.deepEqual(leaks, [], 'no table privilege is granted to any pipeline-side role or PUBLIC');
    const fnExec = (await w.a.query(`select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='ground_truth'
      and (has_function_privilege('anon', p.oid, 'EXECUTE') or has_function_privilege('service_role', p.oid, 'EXECUTE'))`)).rows;
    assert.deepEqual(fnExec, [], 'no GT function is executable by anon/service_role');
  } finally { await w.cleanup(); }
});

test('Supabase-faithful: documents the residual boundary — the postgres role CAN read (pg_read_all_data) but still cannot rewrite history', { skip }, async () => {
  const w = await setupSupabaseLike();
  try {
    await w.a.query(`insert into ground_truth.sources(id,sha256,byte_size,display_name,created_at) values ('s1','${'a'.repeat(64)}',1,'n','t')`);
    await w.a.query(`insert into ground_truth.annotation_revisions(id,source_id,seq,content,digest,author,schema_version,scope,created_at,approved_at) values ('r1','s1',1,'{}','d','op',1,'source','t','t')`);
    assert.equal(await asRoleSql(w.a, ['sb_postgres'], 'select * from ground_truth.annotation_revisions'), 'allowed',
      'KNOWN RESIDUAL: Supabase makes postgres a member of pg_read_all_data, so anything holding the postgres password (SUPABASE_DB_URL, dashboard SQL editor) can read Ground Truth');
    for (const sql of ["update ground_truth.annotation_revisions set content='{\"x\":1}'", 'delete from ground_truth.annotation_revisions', `update ground_truth.sources set sha256='${'b'.repeat(64)}'`]) {
      await w.a.query('set role sb_postgres');
      await assert.rejects(w.a.query(sql), /IMMUTABLE|PROTECTED/, `even postgres cannot: ${sql}`);
      await w.a.query('reset role');
    }
  } finally { await w.cleanup(); }
});

test('Supabase-faithful: Studio and evaluator roles work end to end after a non-superuser migration', { skip, timeout: 120000 }, async () => {
  const w = await setupSupabaseLike();
  const raw = path.join(tmp('ops-'), 'raw'); const open = [];
  try {
    for (const r of ['gt_studio', 'gt_evaluator']) await w.a.query(`alter role ${r} password 'pw_${r}'`);
    const url = role => { const x = new URL(withDb(ADMIN)(w.db)); x.username = role; x.password = `pw_${role}`; return x.toString(); };
    makeVideo(path.join(raw, 'a.mp4'), { seconds: 2, tag: 'sb' });
    const studio = createContext(tmp(), { token: 't', dbUrl: url('gt_studio') }); open.push(studio);
    await reconcile(studio, { roots: [{ dir: raw, prefix: 'raw/' }] });
    const src = studio.db.prepare('select * from sources').get();
    const c = A.emptyContent(); c.segments.push(seg('s', 5, 40)); c.reviewed_ranges.push({ start_frame: 0, end_frame: 60 });
    A.saveDraft(studio.db, src.id, 0, c); A.approve(studio.db, src.id, { expectedVersion: 1, acknowledgeUnresolved: true });
    const ds = D.freezeDataset(studio.db, { name: 'v', sourceIds: [src.id], policy: { seed: 's', ratios: { train: 0, validation: 0, test: 1 } } });
    const pred = E.importPredictions(studio.db, { run_id: 'r', pipeline_version: 'v', sources: [{ source_sha256: src.sha256, events: [{ start_frame: 6, end_frame: 39 }] }] });
    const ev = createContext(tmp(), { token: 't', dbUrl: url('gt_evaluator') }); open.push(ev);
    assert.equal(E.runEvaluation(ev.db, { dataset_id: ds.id, prediction_id: pred.id }).report.metrics.event_recall, 1);
    assert.throws(() => ev.db.prepare('select * from sources').all(), /permission denied/);
    assert.throws(() => studio.db.prepare('delete from sources').run(), /permission denied/);
  } finally { for (const c of open) c.db.close(); await w.cleanup(); }
});

test('db/verify-isolation.sql passes on a correct deployment and FAILS on every kind of pipeline-side grant (safe to rely on live)', { skip, timeout: 120000 }, async () => {
  const verify = readFileSync(new URL('../../db/verify-isolation.sql', import.meta.url), 'utf8');
  const clean = await setupSupabaseLike();
  try { await clean.a.query(verify); } finally { await clean.cleanup(); }          // a correct deployment raises nothing
  const bad = [
    ['grant select on ground_truth.sources to service_role', /relation sources: service_role has SELECT/],
    ['grant usage on schema ground_truth to anon', /schema ground_truth: anon has USAGE/],
    ['grant select (display_name) on ground_truth.sources to authenticated', /column sources\.display_name granted to authenticated/],
    ['grant execute on function ground_truth.reject_append_only() to public', /function reject_append_only: PUBLIC can execute/],
    ['alter default privileges for role sb_postgres in schema ground_truth grant select on tables to service_role', /default privileges of sb_postgres grant to service_role/],
    ['grant gt_studio to service_role', /service_role is a member of gt_studio/],
  ];
  for (const [grant, expected] of bad) {
    const w = await setupSupabaseLike();                                              // fresh deployment per violation: nothing to undo
    try {
      await w.a.query(grant);
      await assert.rejects(w.a.query(verify), expected, grant);
    } finally { await w.cleanup(); }
  }
});
