-- Harden database helper functions and move the unused vector extension out of public.
-- Generated from Supabase security-advisor findings on 2026-09-25.

create schema if not exists extensions;

alter extension vector set schema extensions;

alter function public._set_updated_at()
  set search_path = pg_catalog, public;
alter function public.set_pipeline_runs_updated_at()
  set search_path = pg_catalog, public;
alter function public.set_delivery_runs_updated_at()
  set search_path = pg_catalog, public;
alter function public.set_purchases_updated_at()
  set search_path = pg_catalog, public;
alter function public.set_upload_batches_updated_at()
  set search_path = pg_catalog, public;

revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.source_upload_refresh_batch_trigger() from public, anon, authenticated;
