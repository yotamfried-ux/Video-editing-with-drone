-- Payment tracking for Discover → Checkout → Purchase.
-- Checkout creation inserts a purchase row; the payment event handler marks it paid.

create table if not exists public.purchases (
  id                         uuid primary key default gen_random_uuid(),
  reel_id                    uuid not null references public.reels(id) on delete cascade,
  token                      text not null,
  status                     text not null default 'checkout_created',
  stripe_checkout_session_id text unique,
  stripe_payment_intent_id   text,
  amount_ils                 integer not null,
  currency                   text not null default 'ils',
  customer_email             text,
  metadata                   jsonb not null default '{}'::jsonb,
  created_at                 timestamptz not null default now(),
  paid_at                    timestamptz,
  updated_at                 timestamptz not null default now(),
  constraint purchases_status_chk check (
    status in ('checkout_created','paid','expired','failed','refunded')
  ),
  constraint purchases_amount_chk check (amount_ils > 0)
);

create index if not exists purchases_reel_idx on public.purchases (reel_id, created_at desc);
create index if not exists purchases_status_idx on public.purchases (status, created_at desc);
create index if not exists purchases_token_idx on public.purchases (token, created_at desc);

create or replace function public.set_purchases_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists purchases_updated_at on public.purchases;
create trigger purchases_updated_at
  before insert or update on public.purchases
  for each row execute function public.set_purchases_updated_at();

alter table public.purchases enable row level security;

-- Public clients never access this table directly. The web-api uses the service role.
