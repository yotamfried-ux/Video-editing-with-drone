-- Harden Stripe payment fulfillment for existing environments.
-- Apply through the tracked migration workflow after review; do not run manually
-- against production without a dry run and post-apply verification.

alter table public.payments
  alter column download_token set default gen_random_uuid()::text;

update public.payments
set download_token = gen_random_uuid()::text
where download_token is null or btrim(download_token) = '';

alter table public.payments
  alter column download_token set not null;

alter table public.payments
  add column if not exists receipt_email_sent_at timestamptz,
  add column if not exists receipt_email_claimed_at timestamptz;

create unique index if not exists payments_download_token_uidx
  on public.payments (download_token);

-- Older webhook deliveries may already have inserted duplicate payment events.
-- Retain the newest row for each durable payment/event pair before adding the
-- uniqueness bar required by idempotent webhook and download replays.
delete from public.analytics_events
where id in (
  select id
  from (
    select
      id,
      row_number() over (
        partition by payment_id, event_type
        order by created_at desc nulls last, id desc
      ) as duplicate_rank
    from public.analytics_events
    where payment_id is not null
  ) ranked
  where duplicate_rank > 1
);

-- PostgreSQL permits multiple NULL payment_id values, so non-payment analytics
-- remain valid while each payment event becomes unique.
create unique index if not exists analytics_payment_event_uidx
  on public.analytics_events (payment_id, event_type);
