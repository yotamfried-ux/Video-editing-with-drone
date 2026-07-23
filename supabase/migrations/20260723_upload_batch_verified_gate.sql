-- Durable upload-batch membership and verified-run gate for GAP-015.
-- Depends on the source_uploads and multipart foundation migrations.

create table if not exists public.upload_batches (
  batch_id text primary key check (batch_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  state text not null default 'collecting'
    check (state in ('collecting', 'uploading', 'ready', 'running', 'completed', 'failed', 'cancelled')),
  expected_file_count integer not null check (expected_file_count between 1 and 1000),
  actual_file_count integer not null default 0 check (actual_file_count between 0 and 1000),
  verified_file_count integer not null default 0 check (verified_file_count between 0 and 1000),
  cleanup_pending_count integer not null default 0 check (cleanup_pending_count between 0 and 1000),
  source_kind text not null default 'operator'
    check (source_kind in ('operator', 'android_external', 'gallery', 'api')),
  grouping_kind text not null default 'unassigned'
    check (grouping_kind in ('unassigned', 'one_athlete', 'session_multiple_athletes', 'other')),
  input_manifest jsonb not null default '[]'::jsonb,
  pipeline_run_id uuid references public.pipeline_runs(id) on delete set null,
  locked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists upload_batches_state_updated_idx
  on public.upload_batches (state, updated_at desc);

alter table public.upload_batches enable row level security;
revoke all on table public.upload_batches from anon, authenticated;
grant select, insert, update, delete on table public.upload_batches to service_role;

create or replace function public.set_upload_batches_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists upload_batches_updated_at on public.upload_batches;
create trigger upload_batches_updated_at
  before insert or update on public.upload_batches
  for each row execute function public.set_upload_batches_updated_at();

create or replace function public.register_upload_batch(
  p_batch_id text,
  p_additional_file_count integer,
  p_source_kind text default 'operator',
  p_grouping_kind text default 'unassigned'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_batch public.upload_batches%rowtype;
  v_batch_id text := trim(coalesce(p_batch_id, ''));
  v_source_kind text := lower(trim(coalesce(p_source_kind, 'operator')));
  v_grouping_kind text := lower(trim(coalesce(p_grouping_kind, 'unassigned')));
begin
  if v_batch_id !~ '^[A-Za-z0-9_-]{1,80}$' then
    raise exception 'invalid batch id';
  end if;
  if p_additional_file_count is null or p_additional_file_count not between 1 and 1000 then
    raise exception 'additional file count must be between 1 and 1000';
  end if;
  if v_source_kind not in ('operator', 'android_external', 'gallery', 'api') then
    raise exception 'invalid source kind %', v_source_kind;
  end if;
  if v_grouping_kind not in ('unassigned', 'one_athlete', 'session_multiple_athletes', 'other') then
    raise exception 'invalid grouping kind %', v_grouping_kind;
  end if;

  select * into v_batch
    from public.upload_batches
   where batch_id = v_batch_id
   for update;

  if not found then
    insert into public.upload_batches (
      batch_id,
      state,
      expected_file_count,
      source_kind,
      grouping_kind
    ) values (
      v_batch_id,
      'collecting',
      p_additional_file_count,
      v_source_kind,
      v_grouping_kind
    )
    returning * into v_batch;
  else
    if v_batch.state in ('running', 'completed', 'cancelled') then
      raise exception 'batch % cannot accept files while %', v_batch_id, v_batch.state;
    end if;
    if v_batch.expected_file_count + p_additional_file_count > 1000 then
      raise exception 'batch % would exceed 1000 intended files', v_batch_id;
    end if;

    update public.upload_batches
       set expected_file_count = expected_file_count + p_additional_file_count,
           state = 'collecting',
           source_kind = case
             when source_kind = v_source_kind then source_kind
             else 'operator'
           end,
           grouping_kind = case
             when grouping_kind = 'unassigned' then v_grouping_kind
             when v_grouping_kind = 'unassigned' then grouping_kind
             when grouping_kind = v_grouping_kind then grouping_kind
             else 'other'
           end,
           input_manifest = '[]'::jsonb,
           pipeline_run_id = null,
           locked_at = null
     where batch_id = v_batch_id
     returning * into v_batch;
  end if;

  return jsonb_build_object(
    'batch_id', v_batch.batch_id,
    'state', v_batch.state,
    'expected_file_count', v_batch.expected_file_count,
    'actual_file_count', v_batch.actual_file_count,
    'verified_file_count', v_batch.verified_file_count,
    'cleanup_pending_count', v_batch.cleanup_pending_count,
    'source_kind', v_batch.source_kind,
    'grouping_kind', v_batch.grouping_kind
  );
end;
$$;

revoke all on function public.register_upload_batch(text, integer, text, text) from public, anon, authenticated;
grant execute on function public.register_upload_batch(text, integer, text, text) to service_role;

create or replace function public.refresh_upload_batch_state(p_batch_id text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_batch public.upload_batches%rowtype;
  v_actual integer;
  v_verified integer;
  v_cleanup_pending integer;
  v_manifest jsonb;
  v_next_state text;
begin
  select * into v_batch
    from public.upload_batches
   where batch_id = p_batch_id
   for update;

  if not found then
    return null;
  end if;

  select
    count(*)::integer,
    count(*) filter (
      where status = 'verified'
        and source_size_bytes is not null
        and verified_size_bytes = source_size_bytes
    )::integer,
    count(*) filter (
      where local_cleanup_required
        and local_cleanup_status <> 'confirmed'
    )::integer
  into v_actual, v_verified, v_cleanup_pending
  from public.source_uploads
  where batch_id = p_batch_id;

  select coalesce(jsonb_agg(
    jsonb_build_object(
      'upload_id', id,
      'storage_key', storage_key,
      'source_filename', source_filename,
      'source_size_bytes', source_size_bytes,
      'verified_size_bytes', verified_size_bytes,
      'verified_at', verified_at
    ) order by created_at asc, id asc
  ), '[]'::jsonb)
  into v_manifest
  from public.source_uploads
  where batch_id = p_batch_id
    and status = 'verified'
    and source_size_bytes is not null
    and verified_size_bytes = source_size_bytes;

  v_next_state := case
    when v_batch.state in ('running', 'completed', 'cancelled') then v_batch.state
    when v_actual = v_batch.expected_file_count
      and v_verified = v_batch.expected_file_count
      and v_cleanup_pending = 0
      then 'ready'
    when v_actual = 0 then 'collecting'
    else 'uploading'
  end;

  update public.upload_batches
     set state = v_next_state,
         actual_file_count = v_actual,
         verified_file_count = v_verified,
         cleanup_pending_count = v_cleanup_pending,
         input_manifest = case when v_next_state = 'ready' then v_manifest else '[]'::jsonb end
   where batch_id = p_batch_id
   returning * into v_batch;

  return jsonb_build_object(
    'batch_id', v_batch.batch_id,
    'state', v_batch.state,
    'expected_file_count', v_batch.expected_file_count,
    'actual_file_count', v_batch.actual_file_count,
    'verified_file_count', v_batch.verified_file_count,
    'cleanup_pending_count', v_batch.cleanup_pending_count,
    'input_manifest', v_batch.input_manifest
  );
end;
$$;

revoke all on function public.refresh_upload_batch_state(text) from public, anon, authenticated;
grant execute on function public.refresh_upload_batch_state(text) to service_role;

create or replace function public.source_upload_refresh_batch_trigger()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_batch_id text;
begin
  v_batch_id := case when tg_op = 'DELETE' then old.batch_id else new.batch_id end;
  if exists (select 1 from public.upload_batches where batch_id = v_batch_id) then
    perform public.refresh_upload_batch_state(v_batch_id);
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end;
$$;

drop trigger if exists source_uploads_refresh_batch on public.source_uploads;
create trigger source_uploads_refresh_batch
  after insert or update or delete on public.source_uploads
  for each row execute function public.source_upload_refresh_batch_trigger();

create or replace function public.assert_upload_batch_ready(p_batch_id text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_result jsonb;
  v_state text;
  v_expected integer;
  v_actual integer;
  v_verified integer;
  v_cleanup integer;
  v_manifest jsonb;
begin
  v_result := public.refresh_upload_batch_state(p_batch_id);
  if v_result is null then
    raise exception 'upload batch % not found', p_batch_id;
  end if;

  select state, expected_file_count, actual_file_count, verified_file_count,
         cleanup_pending_count, input_manifest
    into v_state, v_expected, v_actual, v_verified, v_cleanup, v_manifest
    from public.upload_batches
   where batch_id = p_batch_id
   for update;

  if v_state <> 'ready' then
    raise exception 'upload batch % is not ready: state %, intended %, registered %, verified %, cleanup pending %',
      p_batch_id, v_state, v_expected, v_actual, v_verified, v_cleanup;
  end if;
  if jsonb_array_length(v_manifest) <> v_expected then
    raise exception 'upload batch % input manifest mismatch', p_batch_id;
  end if;

  return jsonb_build_object(
    'batch_id', p_batch_id,
    'state', v_state,
    'expected_file_count', v_expected,
    'actual_file_count', v_actual,
    'verified_file_count', v_verified,
    'cleanup_pending_count', v_cleanup,
    'input_manifest', v_manifest
  );
end;
$$;

revoke all on function public.assert_upload_batch_ready(text) from public, anon, authenticated;
grant execute on function public.assert_upload_batch_ready(text) to service_role;

create or replace function public.mark_upload_batch_running(
  p_batch_id text,
  p_pipeline_run_id uuid
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_state text;
begin
  select state into v_state
    from public.upload_batches
   where batch_id = p_batch_id
   for update;

  if not found then
    raise exception 'upload batch % not found', p_batch_id;
  end if;
  if v_state <> 'ready' then
    raise exception 'upload batch % cannot run from state %', p_batch_id, v_state;
  end if;

  update public.upload_batches
     set state = 'running',
         pipeline_run_id = p_pipeline_run_id,
         locked_at = now()
   where batch_id = p_batch_id;
end;
$$;

revoke all on function public.mark_upload_batch_running(text, uuid) from public, anon, authenticated;
grant execute on function public.mark_upload_batch_running(text, uuid) to service_role;
