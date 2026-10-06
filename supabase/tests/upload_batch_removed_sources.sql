-- Behavioural regression: removed / superseded source_uploads rows must not count toward
-- actual/verified/cleanup counts, the frozen manifest, or a rerun.
-- Runs against a scratch Postgres: minimal tables carry only the columns the functions use,
-- then the REAL migration is applied on top.
\set ON_ERROR_STOP on
do $$ begin
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role; end if;
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if;
end $$;

create table pipeline_runs (id uuid primary key default gen_random_uuid(), status text not null default 'queued');
create table upload_batches (
  batch_id text primary key, state text not null default 'collecting',
  expected_file_count integer not null, actual_file_count integer not null default 0,
  verified_file_count integer not null default 0, cleanup_pending_count integer not null default 0,
  source_kind text not null default 'operator', grouping_kind text not null default 'unassigned',
  input_manifest jsonb not null default '[]'::jsonb,
  pipeline_run_id uuid references pipeline_runs(id), locked_at timestamptz
);
create table source_uploads (
  id uuid primary key default gen_random_uuid(), batch_id text not null, storage_key text not null,
  source_filename text, status text not null, source_size_bytes bigint, verified_size_bytes bigint,
  verified_at timestamptz, removed_at timestamptz, superseded_at timestamptz,
  local_cleanup_required boolean not null default false, local_cleanup_status text,
  created_at timestamptz not null default now()
);

\i supabase/migrations/20261006_upload_batch_exclude_removed_sources.sql
\i supabase/migrations/20261006_seal_ready_upload_batches.sql

-- assert_upload_batch_ready is unchanged by the migration; it is copied verbatim from production
-- so the test exercises the exact gate the Run Pipeline button uses.
create or replace function public.assert_upload_batch_ready(p_batch_id text)
returns jsonb language plpgsql security definer set search_path to 'public' as $function$
declare v_result jsonb; v_state text; v_expected integer; v_actual integer; v_verified integer; v_cleanup integer; v_manifest jsonb;
begin
  v_result := public.refresh_upload_batch_state(p_batch_id);
  if v_result is null then raise exception 'upload batch % not found', p_batch_id; end if;
  select state, expected_file_count, actual_file_count, verified_file_count, cleanup_pending_count, input_manifest
    into v_state, v_expected, v_actual, v_verified, v_cleanup, v_manifest
    from public.upload_batches where batch_id = p_batch_id for update;
  if v_state <> 'ready' then
    raise exception 'upload batch % is not ready: state %, intended %, registered %, verified %, cleanup pending %', p_batch_id, v_state, v_expected, v_actual, v_verified, v_cleanup;
  end if;
  if jsonb_array_length(v_manifest) <> v_expected then raise exception 'upload batch % input manifest mismatch', p_batch_id; end if;
  return jsonb_build_object('batch_id', p_batch_id,'state', v_state,'expected_file_count', v_expected,'actual_file_count', v_actual,'verified_file_count', v_verified,'cleanup_pending_count', v_cleanup,'input_manifest', v_manifest);
end; $function$;

insert into upload_batches(batch_id,state,expected_file_count) values ('prod',  'collecting', 24), ('ci','collecting',1);
insert into source_uploads(batch_id,storage_key,source_filename,status,source_size_bytes,verified_size_bytes,verified_at)
  select 'prod','raw/prod/real_'||g||'.MP4','real_'||g||'.MP4','verified',1000000+g,1000000+g,now() from generate_series(1,24) g;
-- 8 removed CI test artifacts that were once attached to the production batch
insert into source_uploads(batch_id,storage_key,source_filename,status,source_size_bytes,verified_size_bytes,verified_at,removed_at)
  select 'prod','raw/prod/ci_'||g||'.mp4','ci_'||g||'.mp4','aborted',500+g,500+g,now(),now() from generate_series(1,8) g;
-- one superseded exact duplicate
insert into source_uploads(batch_id,storage_key,source_filename,status,source_size_bytes,verified_size_bytes,verified_at,superseded_at,local_cleanup_required,local_cleanup_status)
  values ('prod','raw/prod/dup.mp4','dup.mp4','superseded',9,9,now(),now(),true,'pending');

do $$
declare r jsonb; ra jsonb; rr jsonb; run uuid;
begin
  r := refresh_upload_batch_state('prod');
  assert (r->>'actual_file_count')::int = 24, 'actual must be 24, got '||(r->>'actual_file_count');
  assert (r->>'verified_file_count')::int = 24, 'verified must be 24';
  assert (r->>'cleanup_pending_count')::int = 0, 'cleanup pending must ignore superseded rows';
  assert r->>'state' = 'ready', 'state must be ready';
  assert jsonb_array_length(r->'input_manifest') = 24, 'manifest must have 24 entries';
  assert not exists (select 1 from jsonb_array_elements(r->'input_manifest') e where e->>'storage_key' like '%/ci_%' or e->>'storage_key' like '%dup%'), 'removed rows leaked into manifest';

  ra := assert_upload_batch_ready('prod');
  assert jsonb_array_length(ra->'input_manifest') = 24, 'assert_upload_batch_ready manifest';

  -- a retry after a failed attempt must also see exactly 24
  insert into pipeline_runs(status) values ('failed') returning id into run;
  update upload_batches set state='failed', pipeline_run_id=run where batch_id='prod';
  insert into pipeline_runs(status) values ('queued') returning id into run;
  rr := prepare_upload_batch_rerun('prod', run);
  assert jsonb_array_length(rr->'input_manifest') = 24, 'rerun manifest must be 24';
  assert (select state from upload_batches where batch_id='prod') = 'running';
  assert (select actual_file_count from upload_batches where batch_id='prod') = 24;

  -- a batch with fewer active rows than intended must still be refused
  update source_uploads set removed_at=now() where batch_id='prod' and source_filename='real_1.MP4';
  update pipeline_runs set status='failed' where id=run;
  update upload_batches set state='failed' where batch_id='prod';
  begin
    perform prepare_upload_batch_rerun('prod', run);
    raise exception 'rerun accepted a batch with a removed verified source';
  exception when others then
    assert sqlerrm like '%cannot rerun%', 'unexpected error: '||sqlerrm;
  end;
end $$;

-- CI/test upload isolation: with the production batch sealed (ready) and the ONLY batch,
-- a test upload that targets it (explicitly or via app auto-adoption) must be refused,
-- and the batch must be unchanged. A fresh isolated batch still works.
do $$
declare r jsonb; before_state jsonb;
begin
  update upload_batches set state='ready', pipeline_run_id=null, locked_at=null, expected_file_count=24 where batch_id='prod';
  update source_uploads set removed_at=null where batch_id='prod' and source_filename='real_1.MP4';
  r := refresh_upload_batch_state('prod');
  assert r->>'state'='ready' and (r->>'actual_file_count')::int=24, 'precondition: prod ready with 24';
  before_state := r;

  begin
    insert into source_uploads(batch_id,storage_key,source_filename,status,source_size_bytes)
      values ('prod','raw/prod/ci_upl01.mp4','ci_upl01.mp4','pending',96280);
    raise exception 'CI upload was attached to the production-ready batch';
  exception when others then
    assert sqlerrm like '%sealed%', 'unexpected error: '||sqlerrm;
  end;
  begin
    perform register_upload_batch('prod', 8, 'gallery', 'unassigned');
    raise exception 'register_upload_batch reopened a sealed ready batch';
  exception when others then
    assert sqlerrm like '%sealed%', 'unexpected error: '||sqlerrm;
  end;

  r := refresh_upload_batch_state('prod');
  assert r = before_state, 'production batch changed after refused CI upload';
  assert (select count(*) from source_uploads where batch_id='prod' and storage_key like '%upl01%')=0;

  perform register_upload_batch('ci_isolated_run', 1, 'gallery', 'unassigned');
  insert into source_uploads(batch_id,storage_key,source_filename,status,source_size_bytes)
    values ('ci_isolated_run','raw/ci_isolated_run/t.mp4','t.mp4','pending',96280);
  assert (select count(*) from source_uploads where batch_id='ci_isolated_run')=1, 'isolated CI batch must accept its upload';
  assert (select expected_file_count from upload_batches where batch_id='prod')=24;
end $$;
select 'upload batch removed-source regression OK' as result;
