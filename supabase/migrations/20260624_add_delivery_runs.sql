-- Delivery run contract for operator approval → GitHub Actions → Discover publish.
-- This complements pipeline_runs: it tracks what happens after an operator approves
-- a draft and the Deliver Preview workflow starts.

create table if not exists public.delivery_runs (
  id                  uuid primary key default gen_random_uuid(),
  approved_file_id    text not null,
  approved_file_name  text,
  source_video        text,
  status              text not null default 'queued', -- queued | running | discover_published | succeeded | failed | dispatch_failed
  stage               text not null default 'queued',
  github_event        text,
  github_run_id       bigint,
  github_run_url      text,
  discover_reel_id    uuid,
  error               text,
  meta                jsonb not null default '{}'::jsonb,
  approved_at         timestamptz not null default now(),
  started_at          timestamptz,
  finished_at         timestamptz,
  updated_at          timestamptz not null default now()
);

create index if not exists delivery_runs_created_idx on public.delivery_runs (approved_at desc);
create index if not exists delivery_runs_status_idx on public.delivery_runs (status, approved_at desc);
create index if not exists delivery_runs_file_idx on public.delivery_runs (approved_file_id, approved_at desc);

create or replace function public.set_delivery_runs_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists delivery_runs_updated_at on public.delivery_runs;
create trigger delivery_runs_updated_at
  before insert or update on public.delivery_runs
  for each row execute function public.set_delivery_runs_updated_at();

alter table public.delivery_runs enable row level security;

-- Operator app reads delivery runs through web-api using the service role.
-- No public RLS policy is needed here.
