-- PREPARED, NOT APPLIED. Applying it needs the owner's approval (production schema change).
-- Lets a reprocess request be closed as `done` only against evidence for its own athlete, defect and output,
-- instead of the conservative source-wide rule the pipeline uses today. Additive and nullable: existing rows and
-- the current code are unaffected.
alter table public.reprocess_requests
  add column if not exists target_athlete_key     text,   -- athlete the request is about (draft's athlete key)
  add column if not exists original_output_sha256 text,   -- content hash of the draft the request was opened on
  add column if not exists repair_attempt_id      uuid,   -- pipeline run that attempted the repair
  add column if not exists repair_output_sha256   text,   -- content hash of the re-rendered output
  add column if not exists repair_verdict         jsonb;  -- {qa_verdict, publishable, remaining_defects[], checked_at}
-- Rollback: alter table public.reprocess_requests drop column if exists target_athlete_key,
--   drop column if exists original_output_sha256, drop column if exists repair_attempt_id,
--   drop column if exists repair_output_sha256, drop column if exists repair_verdict;
