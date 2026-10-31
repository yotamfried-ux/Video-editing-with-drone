// Isolated Ground Truth database. Every access to SQLite lives behind this module
// so a Postgres adapter can replace it without touching callers.
import { DatabaseSync } from 'node:sqlite';
import { PgDb } from './pgdb.mjs';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { seedSports } from './sports.mjs';

export const SCHEMA_VERSION = 1;

const DDL = `
create table if not exists meta(key text primary key, value text not null);

create table if not exists sources(
  id text primary key,
  sha256 text not null check(length(sha256)=64),
  byte_size integer not null check(byte_size>=0),
  display_name text not null,
  session_key text,
  codec text, width integer, height integer, rotation integer not null default 0,
  fps_num integer, fps_den integer, frame_count integer, duration_ms integer,
  captured_at text,
  ingest_state text not null default 'pending_archive'
    check(ingest_state in ('pending_archive','ready','archive_error','unavailable')),
  archive_key text, archive_verified_at text, archive_error text,
  thumb_path text, proxy_path text,
  created_at text not null,
  unique(sha256, byte_size)
);

create table if not exists source_locations(
  id integer primary key autoincrement,
  source_id text not null references sources(id),
  provider text not null, bucket text, key text not null,
  kind text not null check(kind in ('operational','archive','legacy')),
  observed_at text not null, active integer not null default 1, verified_sha256 text
);
create index if not exists source_locations_src on source_locations(source_id);

create table if not exists upload_batches(
  id text primary key, label text not null, created_at text not null
);
create table if not exists upload_occurrences(
  id integer primary key autoincrement,
  source_id text not null references sources(id),
  batch_id text not null references upload_batches(id),
  original_name text not null, location_key text, created_at text not null,
  unique(source_id, batch_id, original_name)
);

create table if not exists ingestion_jobs(
  id integer primary key autoincrement,
  origin_key text not null, batch_id text, state text not null
    check(state in ('queued','running','done','failed')),
  attempts integer not null default 0, error text, source_id text,
  created_at text not null, updated_at text not null,
  unique(origin_key, batch_id)
);

create table if not exists athletes(
  id text primary key, label text not null, notes text, created_at text not null
);
create table if not exists athlete_appearances(
  id text primary key, athlete_id text not null references athletes(id),
  source_id text not null references sources(id),
  track_label text, uncertain integer not null default 0, confirmed integer not null default 0,
  created_at text not null,
  unique(athlete_id, source_id)
);

create table if not exists annotation_drafts(
  source_id text primary key references sources(id),
  version integer not null, content text not null, base_revision_id text, updated_at text not null
);
create table if not exists annotation_revisions(
  id text primary key, source_id text not null references sources(id),
  seq integer not null, parent_revision_id text, content text not null, digest text not null,
  author text not null, reason text, schema_version integer not null,
  scope text not null check(scope in ('source','interval','segment')),
  created_at text not null, approved_at text not null,
  unique(source_id, seq)
);

create table if not exists dataset_versions(
  id text primary key, name text not null, created_at text not null,
  policy text not null, manifest text not null, digest text not null
);
create table if not exists dataset_members(
  dataset_id text not null references dataset_versions(id),
  source_id text not null, sha256 text not null, revision_id text not null,
  split text not null check(split in ('train','validation','test')),
  primary key(dataset_id, source_id)
);

create table if not exists pipeline_predictions(
  id text primary key, run_id text not null, pipeline_version text not null,
  payload text not null, digest text not null, created_at text not null,
  unique(run_id, pipeline_version)
);
create table if not exists evaluation_runs(
  id text primary key, dataset_id text not null references dataset_versions(id),
  prediction_id text not null references pipeline_predictions(id),
  evaluator_version text not null, params text not null,
  report text not null, digest text not null, created_at text not null
);

create table if not exists edl_records(
  id text primary key, output_id text not null, run_id text not null,
  source_id text, payload text not null, digest text not null, created_at text not null,
  unique(output_id, digest)
);
create table if not exists editing_reports(
  id text primary key, edl_id text, revision_id text, evaluator_version text not null,
  report text not null, digest text not null, created_at text not null
);
create table if not exists crop_proposals(
  id text primary key, source_id text not null, status text not null
    check(status in ('proposal','approved')), payload text not null, created_at text not null
);

create table if not exists sports(
  id text primary key, name_he text not null, name_en text not null,
  enabled integer not null default 1, taxonomy_version integer not null default 1, created_at text not null
);
create table if not exists sport_event_types(
  sport_id text not null references sports(id), key text not null,
  label_he text not null, label_en text not null, parent_key text,
  required_attrs text not null default '[]', enabled integer not null default 1,
  since_version integer not null default 1, created_at text not null,
  primary key(sport_id, key)
);

create view if not exists frozen_revisions as
  select m.dataset_id, m.split, m.sha256, r.id as revision_id, r.digest, r.content
  from dataset_members m join annotation_revisions r on r.id = m.revision_id;
create view if not exists frozen_datasets as
  select id, name, created_at, digest, manifest from dataset_versions;

create table if not exists audit_log(
  id integer primary key autoincrement, at text not null, actor text not null,
  action text not null, subject text, detail text
);
`;

// Append-only guarantees are enforced in the database, not only in application code.
const IMMUTABLE = ['annotation_revisions', 'dataset_versions', 'dataset_members',
  'pipeline_predictions', 'evaluation_runs', 'edl_records', 'editing_reports', 'crop_proposals', 'audit_log'];
const NO_DELETE = ['sources', 'athletes', 'source_locations', 'upload_occurrences', 'sports', 'sport_event_types'];

/**
 * Backend selection: PostgreSQL when `url` (or STUDIO_DB_URL) is given — the schema/roles are applied by
 * scripts/gt-migrate.mjs with an admin connection, never by the running app — otherwise local SQLite under `home`.
 */
export function openDb(home, { url = process.env.STUDIO_DB_URL, ssl } = {}) {
  if (url) {
    const db = new PgDb(url, { ssl });
    const v = db.prepare("select value from meta where key='schema_version'").get();
    if (!v) throw new Error('Ground Truth schema not found: run scripts/gt-migrate.mjs first');
    return db;
  }
  mkdirSync(home, { recursive: true });
  const db = new DatabaseSync(path.join(home, 'studio.sqlite'));
  db.exec('pragma journal_mode=WAL; pragma foreign_keys=on; pragma busy_timeout=5000;');
  db.exec(DDL);
  for (const t of IMMUTABLE) {
    db.exec(`create trigger if not exists ${t}_no_update before update on ${t}
      begin select raise(abort,'IMMUTABLE: ${t} is append-only'); end;
      create trigger if not exists ${t}_no_delete before delete on ${t}
      begin select raise(abort,'IMMUTABLE: ${t} is append-only'); end;`);
  }
  for (const t of NO_DELETE) {
    db.exec(`create trigger if not exists ${t}_no_delete before delete on ${t}
      begin select raise(abort,'PROTECTED: ${t} rows are never deleted'); end;`);
  }
  // Source identity can never be rewritten.
  db.exec(`create trigger if not exists sources_identity_frozen before update of id, sha256, byte_size on sources
    begin select raise(abort,'IMMUTABLE: source identity'); end;`);
  // Additive columns (0002_sports): NULL primary_sport_id = unclassified, never backfilled to surfing.
  addColumn(db, 'sources', 'primary_sport_id', 'text');
  addColumn(db, 'annotation_revisions', 'taxonomy_versions', 'text');
  seedSports(db);
  db.prepare('insert or ignore into meta(key,value) values(?,?)').run('schema_version', String(SCHEMA_VERSION));
  return db;
}

function addColumn(db, table, col, type) {
  if (!db.prepare(`pragma table_info(${table})`).all().some(c => c.name === col)) db.exec(`alter table ${table} add column ${col} ${type}`);
}

export const now = () => new Date().toISOString();

export function tx(db, fn) {
  db.exec('begin immediate');
  try { const r = fn(); db.exec('commit'); return r; }
  catch (e) { db.exec('rollback'); throw e; }
}

export function audit(db, actor, action, subject, detail) {
  db.prepare('insert into audit_log(at,actor,action,subject,detail) values(?,?,?,?,?)')
    .run(now(), actor, action, subject ?? null, detail ? JSON.stringify(detail) : null);
}
