-- Operator "Clean Video Storage": durable audit/lock table and an atomic
-- active-state neutralization function.
--
-- Historical rows are never deleted. Only *active references* that could let a
-- previous batch leak into the next one are marked terminal:
--   * source_uploads that could still be selected/deduplicated/manifested
--   * upload_batches that are collecting/uploading/ready (or stale running)
--   * reprocess_requests that could requeue removed source videos
--   * published/viewed reels whose storage objects were removed
-- Users, auth, profiles, purchases, payments, drafts, pipeline_runs and
-- delivery_runs are untouched.

create table if not exists public.video_storage_cleanup_runs (
  id            uuid primary key default gen_random_uuid(),
  status        text not null default 'running'
                check (status in ('running', 'succeeded', 'failed', 'abandoned')),
  phase         text not null default 'starting',
  requested_by  text not null default 'operator_app',
  before_summary jsonb,
  totals        jsonb not null default '{}'::jsonb,
  verification  jsonb,
  error         text,
  started_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  finished_at   timestamptz
);

-- At most one cleanup may be running at a time (double-submit / repeat guard).
create unique index if not exists video_storage_cleanup_single_running_idx
  on public.video_storage_cleanup_runs ((true))
  where status = 'running';

alter table public.video_storage_cleanup_runs enable row level security;
revoke all on table public.video_storage_cleanup_runs from anon, authenticated;
grant select, insert, update on table public.video_storage_cleanup_runs to service_role;

create or replace function public.neutralize_active_video_state(
  p_run_id uuid,
  p_stale_after interval default interval '7 hours'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_note text := 'video_storage_cleanup:' || p_run_id::text;
  v_live_runs integer;
  v_live_batches integer;
  v_batches integer := 0;
  v_uploads integer := 0;
  v_reedits integer := 0;
  v_reels integer := 0;
begin
  -- Fail closed: never neutralize while a pipeline run/batch is genuinely live.
  select count(*) into v_live_runs
    from public.pipeline_runs
   where status in ('queued', 'running')
     and coalesce(updated_at, queued_at) > v_now - p_stale_after;
  select count(*) into v_live_batches
    from public.upload_batches
   where state = 'running'
     and coalesce(locked_at, updated_at) > v_now - p_stale_after;
  if v_live_runs > 0 or v_live_batches > 0 then
    raise exception 'pipeline_active: % live pipeline run(s), % running batch(es)', v_live_runs, v_live_batches;
  end if;

  -- Batches first so the source_uploads refresh trigger keeps them cancelled.
  update public.upload_batches
     set state = 'cancelled',
         input_manifest = '[]'::jsonb,
         locked_at = null
   where state in ('collecting', 'uploading', 'ready', 'running');
  get diagnostics v_batches = row_count;

  update public.source_uploads
     set status = 'aborted',
         aborted_at = coalesce(aborted_at, v_now),
         removed_at = coalesce(removed_at, v_now),
         last_error = v_note,
         updated_at = v_now
   where status in ('uploading', 'paused', 'completing', 'verified', 'superseded', 'size_mismatch');
  get diagnostics v_uploads = row_count;

  update public.reprocess_requests
     set status = 'cancelled',
         processed_at = coalesce(processed_at, v_now),
         notes = case when notes = '' then v_note else notes || E'\n' || v_note end
   where status in ('pending', 'queued', 'qa_blocked');
  get diagnostics v_reedits = row_count;

  update public.reels
     set status = 'expired',
         expires_at = least(coalesce(expires_at, v_now), v_now)
   where coalesce(status, 'published') in ('published', 'viewed');
  get diagnostics v_reels = row_count;

  return jsonb_build_object(
    'batches_cancelled', v_batches,
    'source_uploads_aborted', v_uploads,
    'reprocess_requests_cancelled', v_reedits,
    'reels_expired', v_reels
  );
end;
$$;

-- Read-only counts of the active references that must be zero after a clean.
create or replace function public.active_video_state_counts(
  p_stale_after interval default interval '7 hours'
)
returns jsonb
language sql
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'source_uploads_active', (select count(*) from public.source_uploads
       where status in ('uploading', 'paused', 'completing', 'verified', 'superseded', 'size_mismatch')),
    'upload_batches_active', (select count(*) from public.upload_batches
       where state in ('collecting', 'uploading', 'ready', 'running')),
    'reprocess_requests_active', (select count(*) from public.reprocess_requests
       where status in ('pending', 'queued', 'qa_blocked')),
    'reels_active', (select count(*) from public.reels
       where coalesce(status, 'published') in ('published', 'viewed')),
    'live_pipeline_runs', (select count(*) from public.pipeline_runs
       where status in ('queued', 'running')
         and coalesce(updated_at, queued_at) > now() - p_stale_after),
    'live_running_batches', (select count(*) from public.upload_batches
       where state = 'running' and coalesce(locked_at, updated_at) > now() - p_stale_after),
    'paid_reels', (select count(distinct reel_id) from public.payments
       where reel_id is not null and status = 'completed')
  );
$$;

revoke all on function public.neutralize_active_video_state(uuid, interval) from public, anon, authenticated;
grant execute on function public.neutralize_active_video_state(uuid, interval) to service_role;
revoke all on function public.active_video_state_counts(interval) from public, anon, authenticated;
grant execute on function public.active_video_state_counts(interval) to service_role;
