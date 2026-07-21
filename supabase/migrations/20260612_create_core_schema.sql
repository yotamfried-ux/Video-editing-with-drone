-- Core schema for SportReel.
-- Safe to re-run: all statements use IF NOT EXISTS / CREATE OR REPLACE.
-- App-user face recognition is intentionally not part of the schema.

-- ─────────────────────────────────────────────
-- 1. REELS
-- ─────────────────────────────────────────────
create table if not exists public.reels (
  id              uuid primary key default gen_random_uuid(),
  sport           text,
  athlete_desc    text,
  recording_date  date,
  source_video    text,
  storage_path    text,            -- Supabase Storage path (bucket: reels)
  stream_uid      text,            -- Cloudflare Stream UID
  status          text default 'published',  -- published | viewed | sold | expired
  token           text unique,     -- short share token
  expires_at      timestamptz,
  created_at      timestamptz default now()
);

alter table public.reels enable row level security;

-- Discovery/share access is token based. Purchase ownership is explicit through
-- checkout and purchase records; it is never inferred from a face in footage.
drop policy if exists "token_access" on public.reels;
create policy "token_access" on public.reels
  for select using (token is not null);

-- ─────────────────────────────────────────────
-- 2. ATHLETE_PROFILES
-- ─────────────────────────────────────────────
create table if not exists public.athlete_profiles (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid unique references auth.users on delete cascade,
  email          text not null,
  name           text,
  push_token     text,             -- Expo push token for notifications
  created_at     timestamptz default now()
);

alter table public.athlete_profiles enable row level security;

-- Athletes read and update only their own non-biometric profile row.
drop policy if exists "athletes_read_own_profile" on public.athlete_profiles;
create policy "athletes_read_own_profile" on public.athlete_profiles
  for select using (user_id = auth.uid());

drop policy if exists "athletes_update_own_profile" on public.athlete_profiles;
create policy "athletes_update_own_profile" on public.athlete_profiles
  for update using (user_id = auth.uid());

-- Trigger: create a profile row the moment a user signs up.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.athlete_profiles (id, user_id, email, created_at)
  values (gen_random_uuid(), new.id, new.email, now())
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ─────────────────────────────────────────────
-- 3. PAYMENTS
-- ─────────────────────────────────────────────
create table if not exists public.payments (
  id                        uuid primary key default gen_random_uuid(),
  reel_id                   uuid references public.reels on delete set null,
  amount_ils                numeric(10,2),
  status                    text default 'pending',   -- pending | completed | failed
  stripe_payment_intent_id  text unique,
  meshulam_transaction_id   text unique,
  download_token            text unique,
  paid_at                   timestamptz,
  created_at                timestamptz default now()
);

alter table public.payments enable row level security;
-- Only service role (web-api) accesses payments — no user-facing RLS needed.

-- ─────────────────────────────────────────────
-- 4. PRICING
-- ─────────────────────────────────────────────
create table if not exists public.pricing (
  sport       text primary key,
  price_ils   numeric(10,2) not null,
  updated_at  timestamptz default now()
);

alter table public.pricing enable row level security;

drop policy if exists "public_read_pricing" on public.pricing;
create policy "public_read_pricing" on public.pricing
  for select using (true);

-- Seed default prices (no-op if rows already exist).
insert into public.pricing (sport, price_ils) values
  ('surfing',        79),
  ('swimming',       79),
  ('skateboarding',  79),
  ('skiing',         89),
  ('snowboarding',   89),
  ('football',       79),
  ('soccer',         79),
  ('basketball',     79),
  ('cycling',        79),
  ('motocross',      89),
  ('parkour',        79),
  ('sport',          79)
on conflict (sport) do nothing;

-- ─────────────────────────────────────────────
-- 5. ANALYTICS_EVENTS
-- ─────────────────────────────────────────────
create table if not exists public.analytics_events (
  id              uuid primary key default gen_random_uuid(),
  event_type      text not null,   -- reel_published | payment_completed | reel_viewed | etc.
  reel_id         uuid,
  payment_id      uuid,
  sport           text,
  recording_date  date,
  revenue_ils     numeric(10,2),
  created_at      timestamptz default now()
);

alter table public.analytics_events enable row level security;
-- Service role only.

-- ─────────────────────────────────────────────
-- 6. SUGGESTIONS
-- ─────────────────────────────────────────────
create table if not exists public.suggestions (
  id          uuid primary key default gen_random_uuid(),
  reel_id     uuid,
  user_id     uuid references auth.users on delete set null,
  message     text not null,
  created_at  timestamptz default now()
);

alter table public.suggestions enable row level security;

drop policy if exists "athletes_insert_suggestions" on public.suggestions;
create policy "athletes_insert_suggestions" on public.suggestions
  for insert with check (user_id = auth.uid());

-- ─────────────────────────────────────────────
-- 7. SUPPORT_TICKETS
-- ─────────────────────────────────────────────
create table if not exists public.support_tickets (
  id              uuid primary key default gen_random_uuid(),
  reel_id         uuid,
  user_id         uuid references auth.users on delete set null,
  message         text not null,
  operator_reply  text,
  status          text default 'open',  -- open | replied | closed
  replied_at      timestamptz,
  created_at      timestamptz default now()
);

alter table public.support_tickets enable row level security;

drop policy if exists "athletes_insert_tickets" on public.support_tickets;
create policy "athletes_insert_tickets" on public.support_tickets
  for insert with check (user_id = auth.uid());

drop policy if exists "athletes_read_own_tickets" on public.support_tickets;
create policy "athletes_read_own_tickets" on public.support_tickets
  for select using (user_id = auth.uid());
