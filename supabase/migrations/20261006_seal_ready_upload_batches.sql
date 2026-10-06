-- A durable batch that is ready/failed/running/completed/cancelled is SEALED: its frozen
-- inputs may not change. New source uploads can only join a batch that is still being
-- collected. This stops any client (operator app, CI test uploads) from attaching files
-- to an existing production-ready batch, which previously reopened it and inflated
-- expected_file_count (24 -> 32).

create or replace function public.source_upload_reject_sealed_batch()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_state text;
begin
  select state into v_state from public.upload_batches where batch_id = new.batch_id;
  if v_state is not null and v_state not in ('collecting', 'uploading') then
    raise exception 'batch % cannot accept files while %: it is sealed; start a new batch',
      new.batch_id, v_state;
  end if;
  return new;
end;
$$;

drop trigger if exists source_uploads_reject_sealed_batch on public.source_uploads;
create trigger source_uploads_reject_sealed_batch
  before insert on public.source_uploads
  for each row execute function public.source_upload_reject_sealed_batch();

create or replace function public.register_upload_batch(p_batch_id text, p_additional_file_count integer, p_source_kind text DEFAULT 'operator'::text, p_grouping_kind text DEFAULT 'unassigned'::text)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
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
    if v_batch.state in ('ready', 'failed', 'running', 'completed', 'cancelled') then
      raise exception 'batch % cannot accept files while %: it is sealed; start a new batch', v_batch_id, v_batch.state;
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
$function$;
revoke all on function public.register_upload_batch(text, integer, text, text) from public, anon, authenticated;
grant execute on function public.register_upload_batch(text, integer, text, text) to service_role;
