-- Pipeline run contract between the operator app, GitHub Actions, and Python pipeline.
-- Unlike pipeline_status (single live row), this table preserves one durable row
-- per requested run so the app can distinguish queued/running/failed/succeeded
-- executions and correlate them to an operator action.

create table if not exists public.pipeline_runs (
  id              uuid primary key default gen_random_uuid(),
  source          text not null default 'manual', -- manual | upload | reset | reprocess | drive_watcher
  status          text not null default 'queued', -- queued | running | succeeded | failed | no_input | dispatch_failed
  stage           text not null default 'queued',
  progress        numeric(6,4) not null default 0,
  github_event    text,
  github_run_id   bigint,
  github_run_url  text,
  input_files     jsonb not null default '[]'::jsonb,
  output_drafts   jsonb not null default '[]'::jsonb,
  error           text,
  meta            jsonb not null default '{}'::jsonb,
  queued_at       timestamptz not null default now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  updated_at      timestamptz not null default now()
);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (queued_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status, queued_at desc);

create or replace function public.set_pipeline_runs_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists pipeline_runs_updated_at on public.pipeline_runs;
create trigger pipeline_runs_updated_at
  before insert or update on public.pipeline_runs
  for each row execute function public.set_pipeline_runs_updated_at();

alter table public.pipeline_runs enable row level security;

-- Operator app reads pipeline runs through web-api using the service role.
-- No public RLS policy is needed here.
