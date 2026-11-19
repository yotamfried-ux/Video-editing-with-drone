-- Cycle 14b (MEM, BLK-14-002): a least-privilege database role for the INFERENCE process.
-- NOT APPLIED by any workflow. Applying it, and issuing the inference key below, is an owner action.
--
-- Why: inference today uses SUPABASE_SERVICE_KEY (service_role bypasses RLS) and can read
-- public.draft_feedback and public.reprocess_requests - earlier-run judgements about the same videos. Strict mode
-- closes those reads in code (pipeline/inference_memory_policy.py); this role closes them in the database, so a
-- code path that forgets the policy is refused by Postgres. GT (schema ground_truth) is already unreadable by
-- service_role (measured 2026-11-19) and is not granted here either.
--
-- Use: PostgREST switches to this role from the JWT `role` claim. The owner signs a key with
-- {"role": "sportreel_inference"} using the project's JWT secret and stores it as the SUPABASE_INFERENCE_KEY
-- secret; strict inference runs use it instead of SUPABASE_SERVICE_KEY (config.SUPABASE_INFERENCE_KEY).
-- Reprocess requests must then be resolved OUTSIDE inference (a separate pre-step with the service key that turns
-- pending requests into a plain list of source keys to re-run; notes never reach inference) and closed after it.
-- Idempotent. Rollback at the bottom.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'sportreel_inference') then
    create role sportreel_inference nologin noinherit;
  end if;
end $$;
grant sportreel_inference to authenticator;

grant usage on schema public to sportreel_inference;

-- Exactly what the inference process writes or reads back about ITS OWN run (run state, drafts it creates,
-- publishability it computes, ingest dedup of the files it is processing). Nothing historical about videos.
grant select, insert, update on public.pipeline_runs        to sportreel_inference;
grant select, insert, update on public.pipeline_status      to sportreel_inference;
grant select, insert, update on public.drafts               to sportreel_inference;
grant select, insert, update on public.draft_publishability to sportreel_inference;
grant select, insert         on public.reels                to sportreel_inference;
grant select, update         on public.source_uploads       to sportreel_inference;
grant select, insert, update on public.source_upload_dedup_audit to sportreel_inference;
grant insert                 on public.athletes             to sportreel_inference;

-- Explicitly NOT readable by inference (history about the same videos), whatever later grants say:
revoke all on public.draft_feedback     from sportreel_inference;
revoke all on public.reprocess_requests from sportreel_inference;
-- Delivery / customer tables are not inference: no grant on athlete_follows, push_tokens,
-- athlete_follow_notifications, delivery_runs, payments, purchases.

-- RLS stays enabled; the role sees rows only through these policies (service_role still bypasses RLS).
do $$
declare t text;
begin
  foreach t in array array['pipeline_runs','pipeline_status','drafts','draft_publishability','reels',
                           'source_uploads','source_upload_dedup_audit','athletes'] loop
    execute format('drop policy if exists inference_access on public.%I', t);
    execute format('create policy inference_access on public.%I to sportreel_inference using (true) with check (true)', t);
  end loop;
end $$;

-- Rollback (run manually if needed):
--   do $$ declare t text; begin foreach t in array array['pipeline_runs','pipeline_status','drafts',
--     'draft_publishability','reels','source_uploads','source_upload_dedup_audit','athletes'] loop
--     execute format('drop policy if exists inference_access on public.%I', t); end loop; end $$;
--   revoke all on all tables in schema public from sportreel_inference;
--   revoke usage on schema public from sportreel_inference;
--   revoke sportreel_inference from authenticator;
--   drop role if exists sportreel_inference;
