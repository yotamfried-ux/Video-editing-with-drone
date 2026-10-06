-- Removed / superseded source uploads (aborted CI artifacts, exact duplicates) must
-- never count toward a durable batch or its frozen input manifest.
-- refresh_upload_batch_state was already corrected in production; this migration
-- records it and applies the same rule to prepare_upload_batch_rerun, which
-- previously counted every source_uploads row (24 verified + 8 removed = 32).

create or replace function public.refresh_upload_batch_state(p_batch_id text)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare v_batch public.upload_batches%rowtype; v_actual integer; v_verified integer; v_cleanup_pending integer; v_manifest jsonb; v_next_state text;
begin
 select * into v_batch from public.upload_batches where batch_id=p_batch_id for update;
 if not found then return null; end if;
 select count(*)::integer,
 count(*) filter(where status='verified' and source_size_bytes is not null and verified_size_bytes=source_size_bytes)::integer,
 count(*) filter(where local_cleanup_required and local_cleanup_status<>'confirmed')::integer
 into v_actual,v_verified,v_cleanup_pending
 from public.source_uploads where batch_id=p_batch_id and removed_at is null and superseded_at is null;
 select coalesce(jsonb_agg(jsonb_build_object('upload_id',id,'storage_key',storage_key,'source_filename',source_filename,'source_size_bytes',source_size_bytes,'verified_size_bytes',verified_size_bytes,'verified_at',verified_at) order by created_at,id),'[]'::jsonb)
 into v_manifest from public.source_uploads where batch_id=p_batch_id and removed_at is null and superseded_at is null and status='verified' and source_size_bytes is not null and verified_size_bytes=source_size_bytes;
 v_next_state:=case when v_batch.state in ('running','completed','cancelled') then v_batch.state when v_actual=v_batch.expected_file_count and v_verified=v_batch.expected_file_count and v_cleanup_pending=0 then 'ready' when v_actual=0 then 'collecting' else 'uploading' end;
 update public.upload_batches set state=v_next_state,actual_file_count=v_actual,verified_file_count=v_verified,cleanup_pending_count=v_cleanup_pending,input_manifest=case when v_next_state='ready' then v_manifest else '[]'::jsonb end where batch_id=p_batch_id returning * into v_batch;
 return jsonb_build_object('batch_id',v_batch.batch_id,'state',v_batch.state,'expected_file_count',v_batch.expected_file_count,'actual_file_count',v_batch.actual_file_count,'verified_file_count',v_batch.verified_file_count,'cleanup_pending_count',v_batch.cleanup_pending_count,'input_manifest',v_batch.input_manifest);
end $function$;

create or replace function public.prepare_upload_batch_rerun(
  p_batch_id text,
  p_pipeline_run_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_batch public.upload_batches%rowtype;
  v_previous_status text;
  v_actual integer;
  v_verified integer;
  v_cleanup integer;
  v_manifest jsonb;
begin
  select * into v_batch from public.upload_batches
   where batch_id = p_batch_id for update;
  if not found then raise exception 'upload batch % not found', p_batch_id; end if;

  if v_batch.pipeline_run_id is not null then
    select status into v_previous_status from public.pipeline_runs
     where id = v_batch.pipeline_run_id;
    if coalesce(v_previous_status, '') in ('queued','dispatching','dispatching_reset','running') then
      raise exception 'upload batch % previous pipeline run % is still active (%)',
        p_batch_id, v_batch.pipeline_run_id, v_previous_status;
    end if;
  end if;

  select count(*)::integer,
         count(*) filter (where status='verified' and source_size_bytes is not null and verified_size_bytes=source_size_bytes)::integer,
         count(*) filter (where local_cleanup_required and local_cleanup_status <> 'confirmed')::integer
    into v_actual,v_verified,v_cleanup
    from public.source_uploads
   where batch_id=p_batch_id and removed_at is null and superseded_at is null;

  if v_actual <> v_batch.expected_file_count or v_verified <> v_batch.expected_file_count or v_cleanup <> 0 then
    raise exception 'upload batch % cannot rerun: intended %, registered %, verified %, cleanup pending %',
      p_batch_id,v_batch.expected_file_count,v_actual,v_verified,v_cleanup;
  end if;

  select coalesce(jsonb_agg(jsonb_build_object(
    'upload_id',id,'storage_key',storage_key,'source_filename',source_filename,
    'source_size_bytes',source_size_bytes,'verified_size_bytes',verified_size_bytes,'verified_at',verified_at
  ) order by created_at asc,id asc),'[]'::jsonb)
  into v_manifest from public.source_uploads
  where batch_id=p_batch_id and removed_at is null and superseded_at is null and status='verified'
    and source_size_bytes is not null and verified_size_bytes=source_size_bytes;

  if jsonb_array_length(v_manifest) <> v_batch.expected_file_count then
    raise exception 'upload batch % rerun manifest mismatch', p_batch_id;
  end if;

  update public.upload_batches set state='running', actual_file_count=v_actual,
    verified_file_count=v_verified, cleanup_pending_count=v_cleanup,
    input_manifest=v_manifest, pipeline_run_id=p_pipeline_run_id, locked_at=now()
  where batch_id=p_batch_id;

  return jsonb_build_object('batch_id',p_batch_id,'expected_file_count',v_batch.expected_file_count,
    'input_manifest',v_manifest,'previous_pipeline_run_id',v_batch.pipeline_run_id);
end;
$$;
revoke all on function public.prepare_upload_batch_rerun(text, uuid) from public, anon, authenticated;
grant execute on function public.prepare_upload_batch_rerun(text, uuid) to service_role;
