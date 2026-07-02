-- Ensure Discover reels remain checkout-eligible unless explicitly expired.
-- Safe behavior:
-- - Future inserts get a 7-day expiry by default.
-- - Existing active Discover reels without an expiry are repaired.
-- - Sold, expired, and already-expiring rows are not changed.

alter table public.reels
  alter column expires_at set default (now() + interval '7 days');

update public.reels
set expires_at = now() + interval '7 days'
where expires_at is null
  and status in ('published', 'viewed');
