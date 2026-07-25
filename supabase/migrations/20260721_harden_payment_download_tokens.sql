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

-- Older webhook retries may already have written duplicate durable events. Keep
-- the oldest row for each paid action before enforcing replay idempotency. NULL
-- payment_id rows are intentionally excluded because they are unrelated events.
with ranked_payment_events as (
  select
    id,
    row_number() over (
      partition by payment_id, event_type
      order by created_at asc nulls last, id asc
    ) as duplicate_rank
  from public.analytics_events
  where payment_id is not null
)
delete from public.analytics_events as event
using ranked_payment_events as ranked
where event.id = ranked.id
  and ranked.duplicate_rank > 1;

-- Webhook retries must not duplicate the same durable analytics event. PostgreSQL
-- permits multiple NULL payment_id values, so non-payment analytics remain valid.
create unique index if not exists analytics_payment_event_uidx
  on public.analytics_events (payment_id, event_type);
