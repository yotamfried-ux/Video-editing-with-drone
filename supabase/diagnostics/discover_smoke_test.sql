-- Discover -> Stripe smoke test seed.
-- Run manually in Supabase SQL Editor when GitHub Actions cannot produce real reels.
-- This creates exactly one published reel that /api/sessions should return.

insert into public.pricing (sport, price_ils, updated_at)
values ('stripe_test', 1000, now())
on conflict (sport)
do update set price_ils = excluded.price_ils, updated_at = now();

with old_reels as (
  select id
  from public.reels
  where source_video = 'discover-stripe-smoke-test'
), deleted_purchases as (
  delete from public.purchases p
  using old_reels r
  where p.reel_id = r.id
  returning p.id
)
delete from public.reels
where source_video = 'discover-stripe-smoke-test';

insert into public.reels (
  sport,
  athlete_desc,
  recording_date,
  source_video,
  storage_path,
  stream_uid,
  status,
  token,
  expires_at,
  created_at
)
values (
  'stripe_test',
  'Stripe smoke test reel',
  current_date,
  'discover-stripe-smoke-test',
  'discover-smoke/placeholder.mp4',
  'discover-smoke-stream',
  'published',
  'stripe_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16),
  now() + interval '7 days',
  now()
)
returning id, token, status, sport, storage_path, expires_at;
