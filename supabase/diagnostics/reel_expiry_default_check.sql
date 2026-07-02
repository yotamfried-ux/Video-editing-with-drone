-- Check the configured default for the reel expiry column.

select column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'reels'
  and column_name = 'expires_at';
