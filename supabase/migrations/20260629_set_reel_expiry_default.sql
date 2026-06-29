alter table public.reels
  alter column expires_at set default (timezone('utc', now()) + make_interval(days => 7));
