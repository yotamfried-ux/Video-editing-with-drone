-- Idempotent large-upload start and exactly-once batch membership.
-- Apply after 20260723_upload_batch_verified_gate.sql.

alter table public.source_uploads
  add column if not exists client_upload_id text,
  add column if not exists batch_membership_registered_at timestamptz;

alter table public.source_uploads
  drop constraint if exists source_uploads_client_upload_id_check;

alter table public.source_uploads
  add constraint source_uploads_client_upload_id_check
  check (
    client_upload_id is null
    or client_upload_id ~ '^[A-Za-z0-9_-]{16,128}$'
  );

create unique index if not exists source_uploads_client_upload_id_unique_idx
  on public.source_uploads (client_upload_id)
  where client_upload_id is not null;

create or replace function public.register_source_upload_batch_membership(
  p_upload_id uuid,
  p_source_kind text default 'operator',
  p_grouping_kind text default 'unassigned'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_upload public.source_uploads%rowtype;
  v_result jsonb;
begin
  select * into v_upload
    from public.source_uploads
   where id = p_upload_id
   for update;

  if not found then
    raise exception 'source upload % not found', p_upload_id;
  end if;

  if v_upload.batch_membership_registered_at is null then
    perform public.register_upload_batch(
      v_upload.batch_id,
      1,
      p_source_kind,
      p_grouping_kind
    );

    update public.source_uploads
       set batch_membership_registered_at = now(),
           updated_at = now()
     where id = p_upload_id
     returning * into v_upload;
  end if;

  v_result := public.refresh_upload_batch_state(v_upload.batch_id);
  if v_result is null then
    raise exception 'upload batch % was not created for source upload %', v_upload.batch_id, p_upload_id;
  end if;

  return jsonb_build_object(
    'upload_id', v_upload.id,
    'client_upload_id', v_upload.client_upload_id,
    'batch_id', v_upload.batch_id,
    'batch_membership_registered_at', v_upload.batch_membership_registered_at,
    'batch', v_result
  );
end;
$$;

revoke all on function public.register_source_upload_batch_membership(uuid, text, text) from public, anon, authenticated;
grant execute on function public.register_source_upload_batch_membership(uuid, text, text) to service_role;
