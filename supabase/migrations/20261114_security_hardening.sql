-- Security hardening found by the 2026-11-14 production-readiness audit. Not data-changing; idempotent.
-- Rollback statements are at the bottom of this file.

-- 1. public.reels was readable by anyone holding the public anon key ("token_access": token is not null),
--    which lists every reel token and, once the preview/full split lands, the path of the paid file.
--    No client reads this table directly: the app and the pipeline go through the service role, which
--    bypasses RLS. Remove the public read.
drop policy if exists "token_access" on public.reels;

-- 2. Trigger function that runs with its owner's rights was callable through the REST API by anon and
--    signed-in users. Triggers fire regardless of EXECUTE; nobody needs to call it.
revoke execute on function public.source_upload_reject_sealed_batch() from public, anon, authenticated;

-- 3. Pin the search_path of the Ground Truth protection triggers so a caller cannot shadow what they call.
alter function ground_truth.reject_append_only() set search_path = ground_truth, pg_temp;
alter function ground_truth.reject_delete_protected() set search_path = ground_truth, pg_temp;
alter function ground_truth.reject_identity_change() set search_path = ground_truth, pg_temp;

-- Rollback (run manually if needed):
--   create policy "token_access" on public.reels for select using (token is not null);
--   grant execute on function public.source_upload_reject_sealed_batch() to anon, authenticated;
--   alter function ground_truth.reject_append_only() reset search_path;
--   alter function ground_truth.reject_delete_protected() reset search_path;
--   alter function ground_truth.reject_identity_change() reset search_path;
