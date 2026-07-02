-- Discover -> Stripe smoke test seed.
-- Run manually in Supabase SQL Editor when GitHub Actions cannot produce real reels.
-- This creates one active published reel that /api/sessions should return.
-- It is intentionally non-destructive: it does not delete or update existing reels.

insert into public.pricing (sport, price_ils, updated_at)
values ('stripe_test', 1000, now())
on conflict (sport)
do update set price_ils = excluded.price_ils, updated_at = now();

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
  'discover-stripe-smoke-test-' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8),
  'discover-smoke/placeholder.mp4',
  'discover-smoke-stream',
  'published',
  'stripe_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16),
  now() + interval '7 days',
  now()
)
returning id, token, status, sport, storage_path, expires_at;
