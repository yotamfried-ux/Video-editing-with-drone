-- Persistent QA re-edit task state.
--
-- A QA-blocked draft is not a terminal state. The pipeline records an explicit
-- task in reprocess_requests with status='qa_blocked'. The operator app shows
-- that task on the Review screen and can promote it to a runnable reprocess
-- request through POST /api/operator/reprocess.

alter table public.reprocess_requests
  add column if not exists origin text not null default 'operator',
  add column if not exists qa_defects jsonb not null default '[]'::jsonb,
  add column if not exists approval_blocked_reasons jsonb not null default '[]'::jsonb,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists max_attempts integer not null default 3,
  add column if not exists last_pipeline_run_id uuid;

create index if not exists reprocess_requests_draft_status_idx
  on public.reprocess_requests (draft_name, status, created_at desc);

create unique index if not exists reprocess_requests_active_qa_block_idx
  on public.reprocess_requests (draft_name)
  where status in ('qa_blocked', 'pending', 'queued') and draft_name is not null;
