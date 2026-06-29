-- Backfill active Discover reels that have no expiry timestamp.

update public.reels
set expires_at = now() + interval '7 days'
where expires_at is null
  and status in ('published', 'viewed')
returning id, token, status, expires_at;
