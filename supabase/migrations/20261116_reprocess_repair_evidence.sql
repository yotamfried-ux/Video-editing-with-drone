-- Applied to production on 2026-11-16 with the owner's approval (migration `reprocess_repair_evidence`).
-- Lets a reprocess request be closed as `done` only against evidence for its own athlete, defect and output
-- (pipeline/reprocess_binding.py), instead of the source-wide rule. Additive and nullable: existing rows keep the
-- source-wide rule. `target_athlete_key` holds a versioned JSON binding - the athlete's actions as
-- [source, start, end, type] plus the original run's athlete key for tracing - because athlete ids are run-local.
alter table public.reprocess_requests
  add column if not exists target_athlete_key     text,   -- JSON binding: the athlete's actions in the footage
  add column if not exists original_output_sha256 text,   -- content hash of the draft the request was opened on
  add column if not exists repair_attempt_id      uuid,   -- pipeline run that attempted the repair
  add column if not exists repair_output_sha256   text,   -- content hash of the re-rendered output
  add column if not exists repair_verdict         jsonb;  -- {qa_verdict, publishable, remaining_defects[], checked_at}
-- Rollback: alter table public.reprocess_requests drop column if exists target_athlete_key,
--   drop column if exists original_output_sha256, drop column if exists repair_attempt_id,
--   drop column if exists repair_output_sha256, drop column if exists repair_verdict;
