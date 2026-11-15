-- Discover preview vs paid full reel, persistent athletes, and "tell me about more clips of this athlete".
-- Additive only: no existing row or column changes meaning.

-- A persistent, non-biometric athlete: an id and the pipeline's text description. Reels of one athlete in
-- one session are linked automatically; athletes are joined across sessions only by an operator decision.
create table if not exists public.athletes (
  id uuid primary key default gen_random_uuid(),
  label text,
  created_at timestamptz not null default now()
);
alter table public.athletes enable row level security;
-- No public policy: read and written by the service role only.

alter table public.reels
  add column if not exists full_storage_path text,           -- clean full-length reel; signed only after a verified payment
  add column if not exists preview_duration_sec numeric,     -- length of the watermarked preview at storage_path
  add column if not exists full_duration_sec numeric,
  add column if not exists athlete_key text,                 -- '<recording date>:<pipeline athlete id>'
  add column if not exists athlete_id uuid references public.athletes(id) on delete set null;
create index if not exists reels_athlete_id_idx on public.reels (athlete_id);
create index if not exists reels_athlete_key_idx on public.reels (athlete_key);

-- The pipeline's draft record carries the athlete key to delivery (another job).
alter table public.drafts add column if not exists athlete_key text;

-- Who bought (optional: a signed-in buyer). Lets the app show the buyer their purchase and gate following.
alter table public.purchases
  add column if not exists user_id uuid references auth.users(id) on delete set null;
create index if not exists purchases_user_id_idx on public.purchases (user_id);

create table if not exists public.athlete_follows (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  athlete_id uuid not null references public.athletes(id) on delete cascade,
  source_reel_id uuid references public.reels(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (user_id, athlete_id)
);
alter table public.athlete_follows enable row level security;
drop policy if exists athlete_follows_read_own on public.athlete_follows;
create policy athlete_follows_read_own on public.athlete_follows
  for select using (auth.uid() = user_id);
-- Created and removed through the web API (which checks the purchase); no client-side write policy.

-- One notification per (follower, reel): delivery re-runs and operator merges never notify twice.
create table if not exists public.athlete_follow_notifications (
  follow_id uuid not null references public.athlete_follows(id) on delete cascade,
  reel_id uuid not null references public.reels(id) on delete cascade,
  sent_at timestamptz not null default now(),
  primary key (follow_id, reel_id)
);
alter table public.athlete_follow_notifications enable row level security;
