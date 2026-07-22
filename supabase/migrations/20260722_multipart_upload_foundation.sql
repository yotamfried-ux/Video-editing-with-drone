-- Durable upload state for resumable R2 multipart uploads.
--
-- Design basis:
-- - Cloudflare R2 multipart state (upload ID + exact part ETags) must live
--   outside a stateless request handler.
-- - AWS S3 multipart limits require >= 5 MiB non-final parts and <= 10,000 parts.
-- - These tables are service-role only. The mobile client never receives direct
--   database credentials and never becomes authoritative for readiness.

create table if not exists public.upload_batches (
  batch_id text primary key,
  session_id text,
  athlete_id text,
  grouping_type text not null default 'session'
    check (grouping_type in ('session', 'athlete', 'mixed', 'other')),
  state text not null default 'collecting'
    check (state in ('collecting', 'uploading', 'ready', 'dispatched', 'completed', 'blocked', 'aborted')),
  expected_file_count integer not null check (expected_file_count between 1 and 20),
  verified_file_count integer not null default 0 check (verified_file_count >= 0),
  owner_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (verified_file_count <= expected_file_count)
);

create table if not exists public.upload_files (
  id uuid primary key default gen_random_uuid(),
  client_upload_id text not null unique,
  batch_id text not null references public.upload_batches(batch_id) on delete restrict,
  r2_key text not null unique,
  upload_id text not null unique,
  source_uri text,
  source_filename text not null,
  source_size_bytes bigint not null check (source_size_bytes > 0),
  source_fingerprint text not null,
  mime_type text not null,
  part_size_bytes bigint not null check (part_size_bytes >= 5242880),
  total_parts integer not null check (total_parts between 1 and 10000),
  uploaded_bytes bigint not null default 0 check (uploaded_bytes >= 0),
  protocol_version text not null default 'r2-multipart-v1',
  state text not null default 'pending'
    check (state in (
      'pending', 'uploading', 'paused', 'source_unavailable', 'completing',
      'verified', 'failed', 'aborting', 'aborted'
    )),
  verified_size_bytes bigint,
  retry_count integer not null default 0 check (retry_count >= 0),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  aborted_at timestamptz,
  check (uploaded_bytes <= source_size_bytes),
  check (verified_size_bytes is null or verified_size_bytes >= 0),
  check (state <> 'verified' or verified_size_bytes = source_size_bytes)
);

create table if not exists public.upload_parts (
  upload_file_id uuid not null references public.upload_files(id) on delete cascade,
  part_number integer not null check (part_number between 1 and 10000),
  etag text not null check (length(trim(etag)) > 0),
  size_bytes bigint not null check (size_bytes > 0),
  retry_count integer not null default 0 check (retry_count >= 0),
  uploaded_at timestamptz not null default now(),
  primary key (upload_file_id, part_number)
);

create index if not exists upload_batches_state_updated_idx
  on public.upload_batches (state, updated_at desc);
create index if not exists upload_files_batch_state_idx
  on public.upload_files (batch_id, state, updated_at desc);
create index if not exists upload_files_incomplete_idx
  on public.upload_files (updated_at)
  where state in ('pending', 'uploading', 'paused', 'source_unavailable', 'completing', 'failed', 'aborting');
create index if not exists upload_parts_file_part_idx
  on public.upload_parts (upload_file_id, part_number);

create or replace function public.touch_upload_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.refresh_upload_batch_rollup(target_batch_id text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  expected_count integer;
  file_count integer;
  verified_count integer;
  active_count integer;
  failed_count integer;
  aborted_count integer;
begin
  select expected_file_count
    into expected_count
    from public.upload_batches
   where batch_id = target_batch_id
   for update;

  if expected_count is null then
    return;
  end if;

  select
    count(*)::integer,
    count(*) filter (where state = 'verified')::integer,
    count(*) filter (where state in ('pending', 'uploading', 'paused', 'source_unavailable', 'completing', 'aborting'))::integer,
    count(*) filter (where state = 'failed')::integer,
    count(*) filter (where state = 'aborted')::integer
  into file_count, verified_count, active_count, failed_count, aborted_count
  from public.upload_files
  where batch_id = target_batch_id;

  update public.upload_batches
     set verified_file_count = verified_count,
         state = case
           when file_count = expected_count and verified_count = expected_count then 'ready'
           when failed_count > 0 then 'blocked'
           when file_count > 0 and aborted_count = file_count then 'aborted'
           when active_count > 0 then 'uploading'
           else 'collecting'
         end,
         updated_at = now()
   where batch_id = target_batch_id
     and state not in ('dispatched', 'completed');
end;
$$;

create or replace function public.refresh_upload_batch_rollup_trigger()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    perform public.refresh_upload_batch_rollup(old.batch_id);
    return old;
  end if;

  perform public.refresh_upload_batch_rollup(new.batch_id);
  if tg_op = 'UPDATE' and old.batch_id is distinct from new.batch_id then
    perform public.refresh_upload_batch_rollup(old.batch_id);
  end if;
  return new;
end;
$$;

create or replace function public.refresh_upload_file_bytes(target_upload_file_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.upload_files
     set uploaded_bytes = coalesce((
       select sum(size_bytes)
       from public.upload_parts
       where upload_file_id = target_upload_file_id
     ), 0),
     updated_at = now()
   where id = target_upload_file_id;
end;
$$;

create or replace function public.refresh_upload_file_bytes_trigger()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    perform public.refresh_upload_file_bytes(old.upload_file_id);
    return old;
  end if;

  perform public.refresh_upload_file_bytes(new.upload_file_id);
  if tg_op = 'UPDATE' and old.upload_file_id is distinct from new.upload_file_id then
    perform public.refresh_upload_file_bytes(old.upload_file_id);
  end if;
  return new;
end;
$$;

create trigger upload_batches_touch_updated_at
before update on public.upload_batches
for each row execute function public.touch_upload_updated_at();

create trigger upload_files_touch_updated_at
before update on public.upload_files
for each row execute function public.touch_upload_updated_at();

create trigger upload_files_refresh_batch_rollup
after insert or update or delete on public.upload_files
for each row execute function public.refresh_upload_batch_rollup_trigger();

create trigger upload_parts_refresh_file_bytes
after insert or update or delete on public.upload_parts
for each row execute function public.refresh_upload_file_bytes_trigger();

alter table public.upload_batches enable row level security;
alter table public.upload_files enable row level security;
alter table public.upload_parts enable row level security;

-- No anon/authenticated policies are intentionally created. These records carry
-- storage authority and are read/written only through the operator web-api with
-- the Supabase service role.
revoke all on function public.refresh_upload_batch_rollup(text) from public, anon, authenticated;
revoke all on function public.refresh_upload_file_bytes(uuid) from public, anon, authenticated;
