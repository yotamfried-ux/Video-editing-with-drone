-- drafts: durable map from draft reel name → raw source videos that produced it.
-- Written by the pipeline at draft-upload time; read when an operator sends a
-- reel back for reprocessing (CI runners are ephemeral, local files don't persist).
create table if not exists public.drafts (
  draft_name   text primary key,
  sources      jsonb not null default '[]'::jsonb,  -- [{"id": drive_file_id, "name": filename}]
  sport        text,
  athlete_desc text,
  created_at   timestamptz not null default now()
);

-- reprocess_requests: operator "send back for re-edit" queue with free-text notes.
-- Inserted by web-api (operator action); consumed by the pipeline at run start.
create table if not exists public.reprocess_requests (
  id           uuid primary key default gen_random_uuid(),
  reel_id      uuid,
  draft_name   text,
  notes        text not null default '',
  status       text not null default 'pending',  -- pending → queued → done | source_not_found
  created_at   timestamptz not null default now(),
  processed_at timestamptz
);

-- Service-role only (pipeline + web-api both use the service key).
alter table public.drafts enable row level security;
alter table public.reprocess_requests enable row level security;
