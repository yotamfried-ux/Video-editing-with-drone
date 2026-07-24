-- Durable multipart source-upload foundation for GAP-013/GAP-014/GAP-015.
-- Depends on 20260723_source_upload_exact_dedup.sql.
-- Real R2 and Android evidence is still required before the gaps can be closed.

alter table public.source_uploads
  drop constraint if exists source_uploads_status_check;

alter table public.source_uploads
  add constraint source_uploads_status_check
  check (status in (
    'uploading',
    'paused',
    'completing',
    'verified',
    'size_mismatch',
    'aborted',
    'superseded',
    'failed'
  ));

alter table public.source_uploads
  add column if not exists upload_protocol text not null default 'single_put'
    check (upload_protocol in ('single_put', 'r2_multipart_v1')),
  add column if not exists multipart_upload_id text,
  add column if not exists part_size_bytes bigint
    check (part_size_bytes is null or part_size_bytes >= 5242880),
  add column if not exists expected_part_count integer
    check (expected_part_count is null or expected_part_count between 1 and 10000),
  add column if not exists completed_part_count integer not null default 0
    check (completed_part_count between 0 and 10000),
  add column if not exists last_activity_at timestamptz,
  add column if not exists aborted_at timestamptz,
  add column if not exists last_error text,
  add column if not exists local_cleanup_required boolean not null default false,
  add column if not exists local_cleanup_status text not null default 'not_required'
    check (local_cleanup_status in ('not_required', 'pending', 'confirmed', 'failed')),
  add column if not exists local_cleanup_confirmed_at timestamptz,
  add column if not exists local_cleanup_error text;

create index if not exists source_uploads_multipart_activity_idx
  on public.source_uploads (upload_protocol, status, last_activity_at)
  where upload_protocol = 'r2_multipart_v1';

create table if not exists public.source_upload_parts (
  source_upload_id uuid not null references public.source_uploads(id) on delete cascade,
  part_number integer not null check (part_number between 1 and 10000),
  etag text not null check (length(trim(etag)) between 1 and 1024),
  size_bytes bigint not null check (size_bytes > 0),
  uploaded_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (source_upload_id, part_number)
);

create index if not exists source_upload_parts_uploaded_idx
  on public.source_upload_parts (source_upload_id, uploaded_at);

alter table public.source_upload_parts enable row level security;
revoke all on table public.source_upload_parts from anon, authenticated;
grant select, insert, update, delete on table public.source_upload_parts to service_role;

create or replace function public.attach_source_multipart_session(
  p_upload_id uuid,
  p_multipart_upload_id text,
  p_part_size_bytes bigint,
  p_expected_part_count integer,
  p_local_cleanup_required boolean default true
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
  v_expected integer;
begin
  if trim(coalesce(p_multipart_upload_id, '')) = '' then
    raise exception 'multipart upload id is required';
  end if;
  if p_part_size_bytes is null or p_part_size_bytes < 5242880 then
    raise exception 'multipart part size must be at least 5 MiB';
  end if;
  if p_expected_part_count is null or p_expected_part_count not between 1 and 10000 then
    raise exception 'multipart part count must be between 1 and 10000';
  end if;

  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;
  if v_upload.source_size_bytes is null or v_upload.source_size_bytes <= 0 then
    raise exception 'source upload % requires a positive source size', p_upload_id;
  end if;
  if v_upload.status <> 'uploading' then
    raise exception 'source upload % is not attachable from status %', p_upload_id, v_upload.status;
  end if;
  if v_upload.multipart_upload_id is not null then
    raise exception 'source upload % already has a multipart session', p_upload_id;
  end if;

  v_expected := ((v_upload.source_size_bytes + p_part_size_bytes - 1) / p_part_size_bytes)::integer;
  if v_expected <> p_expected_part_count then
    raise exception 'multipart part count mismatch: expected %, got %', v_expected, p_expected_part_count;
  end if;

  update public.source_uploads
     set upload_protocol = 'r2_multipart_v1',
         multipart_upload_id = trim(p_multipart_upload_id),
         part_size_bytes = p_part_size_bytes,
         expected_part_count = p_expected_part_count,
         completed_part_count = 0,
         last_activity_at = now(),
         local_cleanup_required = p_local_cleanup_required,
         local_cleanup_status = case when p_local_cleanup_required then 'pending' else 'not_required' end,
         local_cleanup_confirmed_at = null,
         local_cleanup_error = null,
         last_error = null,
         updated_at = now()
   where id = p_upload_id
   returning * into v_upload;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'storage_key', v_upload.storage_key,
    'batch_id', v_upload.batch_id,
    'source_size_bytes', v_upload.source_size_bytes,
    'part_size_bytes', v_upload.part_size_bytes,
    'expected_part_count', v_upload.expected_part_count,
    'status', v_upload.status,
    'upload_protocol', v_upload.upload_protocol,
    'local_cleanup_required', v_upload.local_cleanup_required,
    'local_cleanup_status', v_upload.local_cleanup_status
  );
end;
$$;

revoke all on function public.attach_source_multipart_session(uuid, text, bigint, integer, boolean) from public, anon, authenticated;
grant execute on function public.attach_source_multipart_session(uuid, text, bigint, integer, boolean) to service_role;

create or replace function public.record_source_upload_part(
  p_upload_id uuid,
  p_part_number integer,
  p_etag text,
  p_size_bytes bigint
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
  v_expected_size bigint;
  v_completed integer;
begin
  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;
  if v_upload.upload_protocol <> 'r2_multipart_v1' or v_upload.multipart_upload_id is null then
    raise exception 'source upload % has no multipart session', p_upload_id;
  end if;
  if v_upload.status not in ('uploading', 'paused') then
    raise exception 'source upload % cannot record parts from status %', p_upload_id, v_upload.status;
  end if;
  if p_part_number is null or p_part_number < 1 or p_part_number > v_upload.expected_part_count then
    raise exception 'part number % is outside 1..%', p_part_number, v_upload.expected_part_count;
  end if;
  if trim(coalesce(p_etag, '')) = '' or length(trim(p_etag)) > 1024 then
    raise exception 'part ETag is invalid';
  end if;

  v_expected_size := case
    when p_part_number < v_upload.expected_part_count then v_upload.part_size_bytes
    else v_upload.source_size_bytes - (v_upload.part_size_bytes * (v_upload.expected_part_count - 1))
  end;

  if p_size_bytes is null or p_size_bytes <> v_expected_size then
    raise exception 'part % size mismatch: expected %, got %', p_part_number, v_expected_size, p_size_bytes;
  end if;

  insert into public.source_upload_parts (
    source_upload_id,
    part_number,
    etag,
    size_bytes,
    uploaded_at,
    updated_at
  ) values (
    p_upload_id,
    p_part_number,
    trim(p_etag),
    p_size_bytes,
    now(),
    now()
  )
  on conflict (source_upload_id, part_number) do update
    set etag = excluded.etag,
        size_bytes = excluded.size_bytes,
        uploaded_at = excluded.uploaded_at,
        updated_at = excluded.updated_at;

  select count(*)::integer into v_completed
    from public.source_upload_parts
   where source_upload_id = p_upload_id;

  update public.source_uploads
     set status = 'uploading',
         completed_part_count = v_completed,
         last_activity_at = now(),
         last_error = null,
         updated_at = now()
   where id = p_upload_id;

  return jsonb_build_object(
    'upload_id', p_upload_id,
    'part_number', p_part_number,
    'etag', trim(p_etag),
    'size_bytes', p_size_bytes,
    'completed_part_count', v_completed,
    'expected_part_count', v_upload.expected_part_count
  );
end;
$$;

revoke all on function public.record_source_upload_part(uuid, integer, text, bigint) from public, anon, authenticated;
grant execute on function public.record_source_upload_part(uuid, integer, text, bigint) to service_role;

create or replace function public.begin_source_upload_completion(p_upload_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
  v_count integer;
  v_total bigint;
  v_parts jsonb;
begin
  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;
  if v_upload.upload_protocol <> 'r2_multipart_v1' or v_upload.multipart_upload_id is null then
    raise exception 'source upload % has no multipart session', p_upload_id;
  end if;
  if v_upload.status not in ('uploading', 'paused', 'completing') then
    raise exception 'source upload % cannot complete from status %', p_upload_id, v_upload.status;
  end if;

  select count(*)::integer, coalesce(sum(size_bytes), 0)::bigint
    into v_count, v_total
    from public.source_upload_parts
   where source_upload_id = p_upload_id;

  if v_count <> v_upload.expected_part_count then
    raise exception 'multipart upload is incomplete: expected % parts, found %', v_upload.expected_part_count, v_count;
  end if;
  if v_total <> v_upload.source_size_bytes then
    raise exception 'multipart byte total mismatch: expected %, found %', v_upload.source_size_bytes, v_total;
  end if;

  select jsonb_agg(
    jsonb_build_object(
      'part_number', part_number,
      'etag', etag,
      'size_bytes', size_bytes
    ) order by part_number asc
  ) into v_parts
    from public.source_upload_parts
   where source_upload_id = p_upload_id;

  update public.source_uploads
     set status = 'completing',
         completed_part_count = v_count,
         last_activity_at = now(),
         last_error = null,
         updated_at = now()
   where id = p_upload_id;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'storage_key', v_upload.storage_key,
    'batch_id', v_upload.batch_id,
    'source_size_bytes', v_upload.source_size_bytes,
    'multipart_upload_id', v_upload.multipart_upload_id,
    'part_size_bytes', v_upload.part_size_bytes,
    'expected_part_count', v_upload.expected_part_count,
    'parts', coalesce(v_parts, '[]'::jsonb),
    'local_cleanup_required', v_upload.local_cleanup_required,
    'local_cleanup_status', v_upload.local_cleanup_status
  );
end;
$$;

revoke all on function public.begin_source_upload_completion(uuid) from public, anon, authenticated;
grant execute on function public.begin_source_upload_completion(uuid) to service_role;

create or replace function public.set_source_upload_recoverable_error(
  p_upload_id uuid,
  p_error text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.source_uploads
     set status = case when status = 'completing' then 'uploading' else status end,
         last_error = left(coalesce(p_error, 'multipart operation failed'), 2000),
         last_activity_at = now(),
         updated_at = now()
   where id = p_upload_id
     and status not in ('verified', 'superseded', 'aborted');
end;
$$;

revoke all on function public.set_source_upload_recoverable_error(uuid, text) from public, anon, authenticated;
grant execute on function public.set_source_upload_recoverable_error(uuid, text) to service_role;

create or replace function public.mark_source_upload_aborted(
  p_upload_id uuid,
  p_error text default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.source_uploads
     set status = 'aborted',
         aborted_at = coalesce(aborted_at, now()),
         last_activity_at = now(),
         last_error = nullif(left(coalesce(p_error, ''), 2000), ''),
         updated_at = now()
   where id = p_upload_id
     and status not in ('verified', 'superseded');
end;
$$;

revoke all on function public.mark_source_upload_aborted(uuid, text) from public, anon, authenticated;
grant execute on function public.mark_source_upload_aborted(uuid, text) to service_role;

create or replace function public.record_source_upload_local_cleanup(
  p_upload_id uuid,
  p_status text,
  p_error text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
  v_status text := lower(trim(coalesce(p_status, '')));
begin
  if v_status not in ('not_required', 'confirmed', 'failed') then
    raise exception 'cleanup status must be not_required, confirmed, or failed';
  end if;

  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;
  if v_status = 'confirmed' and v_upload.status <> 'verified' then
    raise exception 'local cleanup cannot be confirmed before upload verification';
  end if;
  if v_status = 'not_required' and v_upload.local_cleanup_required then
    raise exception 'local cleanup is required for source upload %', p_upload_id;
  end if;
  if v_status = 'failed' and trim(coalesce(p_error, '')) = '' then
    raise exception 'cleanup failure requires an error';
  end if;

  update public.source_uploads
     set local_cleanup_status = v_status,
         local_cleanup_confirmed_at = case when v_status in ('confirmed', 'not_required') then now() else null end,
         local_cleanup_error = case when v_status = 'failed' then left(p_error, 2000) else null end,
         updated_at = now()
   where id = p_upload_id
   returning * into v_upload;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'local_cleanup_required', v_upload.local_cleanup_required,
    'local_cleanup_status', v_upload.local_cleanup_status,
    'local_cleanup_confirmed_at', v_upload.local_cleanup_confirmed_at,
    'local_cleanup_error', v_upload.local_cleanup_error
  );
end;
$$;

revoke all on function public.record_source_upload_local_cleanup(uuid, text, text) from public, anon, authenticated;
grant execute on function public.record_source_upload_local_cleanup(uuid, text, text) to service_role;