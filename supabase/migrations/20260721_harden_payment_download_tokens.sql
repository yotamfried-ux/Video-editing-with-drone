-- Ensure every existing and future payment has a non-null UUID download token.
-- Apply through the tracked migration workflow after review; do not run manually
-- against production without a dry run and post-apply verification.

alter table public.payments
  alter column download_token set default gen_random_uuid()::text;

update public.payments
set download_token = gen_random_uuid()::text
where download_token is null or btrim(download_token) = '';

alter table public.payments
  alter column download_token set not null;

create unique index if not exists payments_download_token_uidx
  on public.payments (download_token);
