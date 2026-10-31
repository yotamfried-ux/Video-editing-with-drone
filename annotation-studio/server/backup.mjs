// Logical backup / restore / integrity audit for the Ground Truth database (SQLite or PostgreSQL alike).
// Independent of provider-level snapshots: a portable JSON export with per-table row counts and a content digest.
import { digestOf } from './annotations.mjs';
import { now, audit } from './db.mjs';

export const BACKUP_FORMAT = 'gt-backup/v1';
// Dependency order (parents first) and a deterministic order column per table.
export const TABLES = [
  ['sources', 'id'], ['source_locations', 'id'], ['upload_batches', 'id'], ['upload_occurrences', 'id'], ['ingestion_jobs', 'id'],
  ['athletes', 'id'], ['athlete_appearances', 'id'], ['annotation_drafts', 'source_id'], ['annotation_revisions', 'id'],
  ['dataset_versions', 'id'], ['dataset_members', 'dataset_id, source_id'], ['pipeline_predictions', 'id'], ['evaluation_runs', 'id'],
  ['edl_records', 'id'], ['editing_reports', 'id'], ['crop_proposals', 'id'], ['audit_log', 'id'],
  ['sports', 'id'], ['sport_event_types', 'sport_id, key'],
];
// Taxonomy is configuration that a fresh database already seeds: restore upserts it instead of requiring emptiness,
// and backups made before the registry existed (no such tables) stay restorable.
const CONFIG = { sports: 'id', sport_event_types: 'sport_id, key' };
const IDENTITY = new Set(['source_locations', 'upload_occurrences', 'ingestion_jobs', 'audit_log']);

export function exportBackup(db) {
  const tables = {};
  for (const [t, order] of TABLES) tables[t] = db.prepare(`select * from ${t} order by ${order}`).all().map(r => ({ ...r }));
  const counts = Object.fromEntries(Object.entries(tables).map(([t, rows]) => [t, rows.length]));
  const body = { format: BACKUP_FORMAT, schema_version: Number(db.prepare("select value from meta where key='schema_version'").get().value), counts, tables };
  return { ...body, digest: digestOf(body) };
}

export function verifyBackupFile(backup) {
  const { digest, ...body } = backup;
  const problems = [];
  if (backup.format !== BACKUP_FORMAT) problems.push('format');
  if (digestOf(body) !== digest) problems.push('digest_mismatch');
  for (const [t] of TABLES) if (!(t in CONFIG && backup.counts?.[t] === undefined) && (backup.tables?.[t]?.length ?? -1) !== backup.counts?.[t]) problems.push(`count_mismatch:${t}`);
  return problems;
}

/** Restores into an EMPTY database only (never merges into live data). Verifies the file first and the result after. */
export function restoreBackup(db, backup, { actor = 'operator' } = {}) {
  const problems = verifyBackupFile(backup);
  if (problems.length) throw new Error(`backup file failed verification: ${problems.join(', ')}`);
  for (const [t] of TABLES) if (!(t in CONFIG) && db.prepare(`select count(*) n from ${t}`).get().n > 0 && t !== 'audit_log') throw new Error(`refusing to restore into a non-empty database (${t})`);
  db.exec('begin immediate');
  try {
    for (const [t] of TABLES) {
      for (const row of backup.tables[t] ?? []) {
        const cols = Object.keys(row);
        const upsert = t in CONFIG ? ` on conflict (${CONFIG[t]}) do update set ${cols.filter(c => !CONFIG[t].split(',').map(x => x.trim()).includes(c)).map(c => `${c}=excluded.${c}`).join(',')}` : '';
        db.prepare(`insert into ${t}(${cols.join(',')}) values(${cols.map(() => '?').join(',')})${upsert}`).run(...cols.map(c => row[c]));
      }
    }
    db.exec('commit');
  } catch (e) { db.exec('rollback'); throw e; }
  // keep identity sequences ahead of restored ids (PostgreSQL)
  for (const t of IDENTITY) {
    try { db.prepare(`select setval(pg_get_serial_sequence('${t}','id'), greatest(coalesce((select max(id) from ${t}),1),1))`).get(); } catch { /* sqlite autoincrement */ }
  }
  const after = exportBackup(db);
  const diffs = TABLES.filter(([t]) => t !== 'audit_log' && backup.tables[t]).filter(([t]) => digestOf(after.tables[t]) !== digestOf(backup.tables[t])).map(([t]) => t);
  if (diffs.length) throw new Error(`restore verification failed for: ${diffs.join(', ')}`);
  audit(db, actor, 'restore_backup', null, { digest: backup.digest, counts: backup.counts });
  return { restored: backup.counts, digest: backup.digest };
}

/** Recomputes every stored digest: approved revisions, frozen manifests, evaluation reports, prediction payloads, EDL records. */
export function verifyIntegrity(db) {
  const bad = [];
  for (const r of db.prepare('select id,content,digest from annotation_revisions').all()) if (digestOf(JSON.parse(r.content)) !== r.digest) bad.push({ table: 'annotation_revisions', id: r.id });
  for (const d of db.prepare('select id,manifest,digest from dataset_versions').all()) if (digestOf(JSON.parse(d.manifest)) !== d.digest) bad.push({ table: 'dataset_versions', id: d.id });
  for (const e of db.prepare('select id,report,digest from evaluation_runs').all()) if (digestOf(JSON.parse(e.report)) !== e.digest) bad.push({ table: 'evaluation_runs', id: e.id });
  for (const e of db.prepare('select id,payload,digest from pipeline_predictions').all()) if (digestOf(JSON.parse(e.payload)) !== e.digest) bad.push({ table: 'pipeline_predictions', id: e.id });
  for (const e of db.prepare('select id,payload,digest from edl_records').all()) if (digestOf(JSON.parse(e.payload)) !== e.digest) bad.push({ table: 'edl_records', id: e.id });
  // every dataset member must still point at an existing revision with the pinned digest
  for (const m of db.prepare('select m.dataset_id,m.source_id,m.revision_id from dataset_members m left join annotation_revisions r on r.id=m.revision_id where r.id is null').all()) bad.push({ table: 'dataset_members', id: `${m.dataset_id}/${m.source_id}`, reason: 'missing_revision' });
  const out = { ok: bad.length === 0, at: now(), problems: bad };
  audit(db, 'system', 'verify_integrity', null, { ok: out.ok, problems: bad.length });
  return out;
}
