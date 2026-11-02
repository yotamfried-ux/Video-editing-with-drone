-- Least-privilege roles for the Ground Truth schema. Run by an administrator, never by the pipeline.
-- Placeholders: __SCHEMA__ (default ground_truth). Passwords are NOT set here; set them out-of-band
-- (e.g. `alter role gt_studio password :'pw'` via psql variables) so no secret is ever committed or logged.
--
-- Principals
--   (owner)       the migration role (on Supabase: `postgres`) owns the schema and objects; no extra owner role is needed
--   gt_studio     LOGIN    the Annotation Studio server: read/write working tables, INSERT-only on append-only tables
--   gt_evaluator  LOGIN    evaluator: SELECT on frozen views + predictions, INSERT evaluation_runs; nothing else
--   pipeline      (none)   the production pipeline/web-api roles (anon, authenticated, service_role, ...) get NOTHING

set local search_path = __SCHEMA__;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'gt_studio')    then create role gt_studio login noinherit; end if;
  if not exists (select 1 from pg_roles where rolname = 'gt_evaluator') then create role gt_evaluator login noinherit; end if;
end $$;

alter role gt_studio set search_path = __SCHEMA__;
alter role gt_evaluator set search_path = __SCHEMA__;

-- 1. Nobody from the production side can see or use the schema or anything in it.
do $$
declare r text;
begin
  foreach r in array array['anon','authenticated','service_role','authenticator','supabase_auth_admin','supabase_storage_admin'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on schema __SCHEMA__ from %I', r);
      execute format('revoke all on all tables in schema __SCHEMA__ from %I', r);
      execute format('revoke all on all sequences in schema __SCHEMA__ from %I', r);
      execute format('revoke all on all functions in schema __SCHEMA__ from %I', r);
    end if;
  end loop;
end $$;
revoke all on schema __SCHEMA__ from public;
revoke all on all tables in schema __SCHEMA__ from public;
revoke all on all functions in schema __SCHEMA__ from public;

-- 3. Studio server
grant usage on schema __SCHEMA__ to gt_studio;
grant select, insert, update on sources, athletes, athlete_appearances, annotation_drafts, ingestion_jobs, meta to gt_studio;
grant select, insert, update on source_locations, upload_batches, sports, sport_event_types, cloud_objects to gt_studio;
grant select, insert on upload_occurrences to gt_studio;
grant select, insert on annotation_revisions, dataset_versions, dataset_members, pipeline_predictions, evaluation_runs,
                        edl_records, editing_reports, crop_proposals, audit_log to gt_studio;
grant select on schema_migrations to gt_studio;
grant select on frozen_revisions, frozen_datasets to gt_studio;
grant usage, select on all sequences in schema __SCHEMA__ to gt_studio;
-- gt_studio holds NO delete privilege on any table: deletion is not an application operation.

-- 4. Evaluator: frozen ground truth + predictions, writes only its own results
grant usage on schema __SCHEMA__ to gt_evaluator;
grant select on frozen_revisions, frozen_datasets to gt_evaluator;
grant select on pipeline_predictions, meta to gt_evaluator;
grant select, insert on evaluation_runs to gt_evaluator;
grant insert on audit_log to gt_evaluator;
grant usage on all sequences in schema __SCHEMA__ to gt_evaluator;

-- 5. Row-level security as a second fence for roles without BYPASSRLS (service_role bypasses RLS by design,
--    so privileges above — not RLS — are what stop it).
do $$ declare t record; begin
  for t in select tablename from pg_tables where schemaname = '__SCHEMA__' loop
    execute format('alter table __SCHEMA__.%I enable row level security', t.tablename);
    execute format('drop policy if exists studio_all on __SCHEMA__.%I', t.tablename);
    execute format('create policy studio_all on __SCHEMA__.%I for all to gt_studio using (true) with check (true)', t.tablename);
  end loop;
  execute 'drop policy if exists evaluator_read on __SCHEMA__.dataset_members';
  execute 'create policy evaluator_read on __SCHEMA__.dataset_members for select to gt_evaluator using (true)';
  execute 'drop policy if exists evaluator_read on __SCHEMA__.dataset_versions';
  execute 'create policy evaluator_read on __SCHEMA__.dataset_versions for select to gt_evaluator using (true)';
  execute 'drop policy if exists evaluator_read on __SCHEMA__.annotation_revisions';
  execute 'create policy evaluator_read on __SCHEMA__.annotation_revisions for select to gt_evaluator using (true)';
  execute 'drop policy if exists evaluator_read on __SCHEMA__.pipeline_predictions';
  execute 'create policy evaluator_read on __SCHEMA__.pipeline_predictions for select to gt_evaluator using (true)';
  execute 'drop policy if exists evaluator_read on __SCHEMA__.meta';
  execute 'create policy evaluator_read on __SCHEMA__.meta for select to gt_evaluator using (true)';
  execute 'drop policy if exists evaluator_audit on __SCHEMA__.audit_log';
  execute 'create policy evaluator_audit on __SCHEMA__.audit_log for insert to gt_evaluator with check (true)';
  execute 'drop policy if exists evaluator_write on __SCHEMA__.evaluation_runs';
  execute 'create policy evaluator_write on __SCHEMA__.evaluation_runs for all to gt_evaluator using (true) with check (true)';
end $$;
