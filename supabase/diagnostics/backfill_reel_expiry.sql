-- Preview and repair active Discover reels that have no expiry timestamp.
-- Review the preview first. Run the update only when the returned rows should stay checkout-eligible.

select id, token, status, created_at, expires_at
from public.reels
where expires_at is null
  and status in ('published', 'viewed')
order by created_at desc;

-- Repair statement used by the migration:
-- update public.reels
-- set expires_at = now() + interval '7 days'
-- where expires_at is null
--   and status in ('published', 'viewed')
-- returning id, token, status, expires_at;
