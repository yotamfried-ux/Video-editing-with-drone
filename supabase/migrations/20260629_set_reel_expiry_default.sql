alter table public.reels
  alter column expires_at set default (timezone('utc', now()) + make_interval(days => 7));

update public.reels
set expires_at = timezone('utc', now()) + make_interval(days => 7)
where expires_at is null
  and status in ('published', 'viewed');
