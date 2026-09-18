-- Central, serverless-safe API rate limiting backed by Supabase.
-- This replaces reliance on a single external Redis endpoint while preserving
-- centralized enforcement across Vercel function instances.

create table if not exists public.api_rate_limit_windows (
  limiter_key text not null,
  window_start timestamptz not null,
  hit_count integer not null check (hit_count > 0),
  primary key (limiter_key, window_start)
);

alter table public.api_rate_limit_windows enable row level security;
revoke all on table public.api_rate_limit_windows from public, anon, authenticated;
grant select, insert, update, delete on table public.api_rate_limit_windows to service_role;

create or replace function public.consume_api_rate_limit(
  p_key text,
  p_limit integer,
  p_window_seconds integer
)
returns table (
  allowed boolean,
  remaining integer,
  reset_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_window_start timestamptz;
  v_count integer;
begin
  if p_key is null or btrim(p_key) = '' then
    raise exception 'rate-limit key is required';
  end if;
  if p_limit is null or p_limit < 1 then
    raise exception 'rate-limit limit must be positive';
  end if;
  if p_window_seconds is null or p_window_seconds < 1 then
    raise exception 'rate-limit window must be positive';
  end if;

  v_window_start :=
    to_timestamp(
      floor(extract(epoch from clock_timestamp()) / p_window_seconds)
      * p_window_seconds
    );

  insert into public.api_rate_limit_windows(limiter_key, window_start, hit_count)
  values (p_key, v_window_start, 1)
  on conflict (limiter_key, window_start)
  do update
    set hit_count = public.api_rate_limit_windows.hit_count + 1
  returning hit_count into v_count;

  -- Keep only a small amount of history per key.
  delete from public.api_rate_limit_windows
  where limiter_key = p_key
    and window_start < v_window_start - make_interval(secs => p_window_seconds * 2);

  return query
  select
    v_count <= p_limit,
    greatest(p_limit - v_count, 0),
    v_window_start + make_interval(secs => p_window_seconds);
end
$$;

revoke all on function public.consume_api_rate_limit(text, integer, integer)
  from public, anon, authenticated;
grant execute on function public.consume_api_rate_limit(text, integer, integer)
  to service_role;
