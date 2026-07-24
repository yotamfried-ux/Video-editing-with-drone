-- Explicit size-evidence policy for legacy single-PUT uploads.
-- Large Android SD/USB multipart uploads keep a client-declared source size.
-- A legacy gallery PUT that cannot expose source size before upload may adopt the
-- completed R2 object's HEAD Content-Length, but the weaker evidence is recorded.

alter table public.source_uploads
  add column if not exists source_size_evidence text not null default 'client_declared';

alter table public.source_uploads
  drop constraint if exists source_uploads_source_size_evidence_check;

alter table public.source_uploads
  add constraint source_uploads_source_size_evidence_check
  check (source_size_evidence in ('unknown', 'client_declared', 'r2_head_adopted'));

update public.source_uploads
   set source_size_evidence = 'unknown'
 where source_size_bytes is null
   and source_size_evidence = 'client_declared';

create or replace function public.verify_source_upload(
  p_storage_key text,
  p_verified_size_bytes bigint
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
begin
  if p_verified_size_bytes is null or p_verified_size_bytes < 0 then
    raise exception 'verified size must be a non-negative integer';
  end if;

  select *
    into v_upload
    from public.source_uploads
   where storage_key = p_storage_key
   for update;

  if not found then
    raise exception 'source upload for storage key % not found', p_storage_key;
  end if;

  if v_upload.status = 'superseded' then
    raise exception 'source upload % is superseded by %', v_upload.id, v_upload.canonical_upload_id;
  end if;

  if v_upload.source_size_bytes is null then
    if v_upload.upload_protocol <> 'single_put' then
      raise exception 'multipart source upload % requires a client-declared source size', v_upload.id;
    end if;

    update public.source_uploads
       set source_size_bytes = p_verified_size_bytes,
           source_size_evidence = 'r2_head_adopted',
           updated_at = now()
     where id = v_upload.id
     returning * into v_upload;
  end if;

  if v_upload.source_size_bytes <> p_verified_size_bytes then
    update public.source_uploads
       set status = 'size_mismatch',
           verified_size_bytes = p_verified_size_bytes,
           updated_at = now()
     where id = v_upload.id
     returning * into v_upload;

    return jsonb_build_object(
      'upload_id', v_upload.id,
      'status', v_upload.status,
      'source_size_bytes', v_upload.source_size_bytes,
      'source_size_evidence', v_upload.source_size_evidence,
      'verified_size_bytes', v_upload.verified_size_bytes,
      'verified_at', v_upload.verified_at
    );
  end if;

  update public.source_uploads
     set status = 'verified',
         verified_size_bytes = p_verified_size_bytes,
         verified_at = coalesce(verified_at, now()),
         updated_at = now()
   where id = v_upload.id
   returning * into v_upload;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'status', v_upload.status,
    'source_size_bytes', v_upload.source_size_bytes,
    'source_size_evidence', v_upload.source_size_evidence,
    'verified_size_bytes', v_upload.verified_size_bytes,
    'verified_at', v_upload.verified_at
  );
end;
$$;

revoke all on function public.verify_source_upload(text, bigint) from public, anon, authenticated;
grant execute on function public.verify_source_upload(text, bigint) to service_role;
