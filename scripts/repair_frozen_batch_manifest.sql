-- Narrow, guarded repair: restore upload_batches.input_manifest for ONE failed batch from
-- the immutable pipeline_runs.input_files of the run that owns it.
--
-- Applied once on 2026-10-09 (batch_2026-10-03T12-19-52_ttgvat95 / run 61d0014a-...).
-- Touches only upload_batches.input_manifest (updated_at bumps via trigger). It never writes
-- source_uploads, pipeline_runs, or storage. Single statement => atomic; every predicate below
-- is re-checked at write time, so a changed row simply updates 0 rows.
--
-- Parameters: replace the three literals (batch, run, expected updated_at captured beforehand).

with r as (
  select id, input_files from pipeline_runs
  where id = '61d0014a-daab-4a03-9319-69a0be691ef1' and status = 'failed'
    and jsonb_typeof(input_files) = 'array' and jsonb_array_length(input_files) = 24
), chk as (
  select r.input_files,
    (select count(*) from jsonb_array_elements(r.input_files) e
       join source_uploads s on s.id = (e->>'upload_id')::uuid
      where s.batch_id = 'batch_2026-10-03T12-19-52_ttgvat95' and s.status = 'verified'
        and s.canonical_upload_id = s.id and s.superseded_at is null and s.removed_at is null
        and s.aborted_at is null and s.removal_error is null
        and s.storage_key = e->>'storage_key' and s.source_filename = e->>'source_filename'
        and s.source_size_bytes = (e->>'source_size_bytes')::bigint
        and s.verified_size_bytes = (e->>'verified_size_bytes')::bigint
        and s.verified_size_bytes = s.source_size_bytes
        and s.verified_at = (e->>'verified_at')::timestamptz) as matched,
    (select count(distinct e->>'upload_id') from jsonb_array_elements(r.input_files) e) as distinct_ids,
    (select count(*) from upload_batches where pipeline_run_id = r.id) as linked
  from r
)
update upload_batches b set input_manifest = chk.input_files
from chk
where b.batch_id = 'batch_2026-10-03T12-19-52_ttgvat95'
  and b.state = 'failed' and b.pipeline_run_id = '61d0014a-daab-4a03-9319-69a0be691ef1'
  and b.input_manifest = '[]'::jsonb                       -- only ever fills an EMPTY manifest
  and b.expected_file_count = 24 and b.actual_file_count = 24 and b.verified_file_count = 24
  and b.cleanup_pending_count = 0
  and b.updated_at = '2026-10-06T23:41:41.52152+00:00'::timestamptz   -- optimistic concurrency
  and chk.matched = 24 and chk.distinct_ids = 24 and chk.linked = 1
returning b.batch_id, jsonb_array_length(b.input_manifest) as manifest_entries;

-- ROLLBACK (restores the exact pre-repair value; original row: state=failed, input_manifest=[],
-- pipeline_run_id=61d0014a-..., locked_at=2026-10-06T19:51:29.556563+00, updated_at=2026-10-06T23:41:41.52152+00):
--   update upload_batches set input_manifest = '[]'::jsonb
--    where batch_id = 'batch_2026-10-03T12-19-52_ttgvat95' and state = 'failed'
--      and pipeline_run_id = '61d0014a-daab-4a03-9319-69a0be691ef1';
-- (updated_at will advance by trigger; it is not a functional field.)
--
-- HAZARD: public.source_upload_refresh_batch_trigger calls refresh_upload_batch_state on ANY
-- insert/update/delete of source_uploads rows of the batch. For a 'failed' batch whose counts are
-- all satisfied that function sets state='ready' and re-derives the manifest ordered by
-- created_at, which would make /pipeline/retry reject the batch (state != failed). Do not touch
-- source_uploads rows of this batch before the retry is dispatched.
