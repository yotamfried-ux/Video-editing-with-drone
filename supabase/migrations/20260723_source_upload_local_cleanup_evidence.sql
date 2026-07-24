-- Durable phone-storage cleanup evidence for large source uploads.
-- The client may report only app-owned SportReel temporary artifacts. The original
-- SD/USB content URI must remain preserved and is never a cleanup target.

alter table public.source_uploads
  add column if not exists local_cleanup_artifact_count integer
    check (local_cleanup_artifact_count is null or local_cleanup_artifact_count >= 0),
  add column if not exists local_cleanup_reclaimed_bytes bigint
    check (local_cleanup_reclaimed_bytes is null or local_cleanup_reclaimed_bytes >= 0),
  add column if not exists local_cleanup_source_preserved boolean,
  add column if not exists local_cleanup_checked_at timestamptz;

create or replace function public.record_source_upload_local_cleanup_evidence(
  p_upload_id uuid,
  p_status text,
  p_artifact_count integer,
  p_reclaimed_bytes bigint,
  p_source_preserved boolean,
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
  if p_artifact_count is null or p_artifact_count < 0 then
    raise exception 'cleanup artifact count must be a non-negative integer';
  end if;
  if p_reclaimed_bytes is null or p_reclaimed_bytes < 0 then
    raise exception 'cleanup reclaimed bytes must be a non-negative integer';
  end if;
  if p_source_preserved is distinct from true then
    raise exception 'the selected SD/USB source must remain preserved';
  end if;
  if v_status = 'failed' and trim(coalesce(p_error, '')) = '' then
    raise exception 'cleanup failure requires an error';
  end if;

  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;
  if v_status = 'confirmed'
     and v_upload.status not in ('verified', 'aborted', 'failed', 'size_mismatch') then
    raise exception 'local cleanup cannot be confirmed while upload status is %', v_upload.status;
  end if;
  if v_status = 'not_required' and v_upload.local_cleanup_required then
    raise exception 'local cleanup is required for source upload %', p_upload_id;
  end if;

  update public.source_uploads
     set local_cleanup_status = v_status,
         local_cleanup_confirmed_at = case when v_status in ('confirmed', 'not_required') then now() else null end,
         local_cleanup_error = case when v_status = 'failed' then left(p_error, 2000) else null end,
         local_cleanup_artifact_count = p_artifact_count,
         local_cleanup_reclaimed_bytes = p_reclaimed_bytes,
         local_cleanup_source_preserved = p_source_preserved,
         local_cleanup_checked_at = now(),
         updated_at = now()
   where id = p_upload_id
   returning * into v_upload;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'upload_status', v_upload.status,
    'local_cleanup_required', v_upload.local_cleanup_required,
    'local_cleanup_status', v_upload.local_cleanup_status,
    'local_cleanup_confirmed_at', v_upload.local_cleanup_confirmed_at,
    'local_cleanup_error', v_upload.local_cleanup_error,
    'local_cleanup_artifact_count', v_upload.local_cleanup_artifact_count,
    'local_cleanup_reclaimed_bytes', v_upload.local_cleanup_reclaimed_bytes,
    'local_cleanup_source_preserved', v_upload.local_cleanup_source_preserved,
    'local_cleanup_checked_at', v_upload.local_cleanup_checked_at
  );
end;
$$;

revoke all on function public.record_source_upload_local_cleanup_evidence(uuid, text, integer, bigint, boolean, text) from public, anon, authenticated;
grant execute on function public.record_source_upload_local_cleanup_evidence(uuid, text, integer, bigint, boolean, text) to service_role;
