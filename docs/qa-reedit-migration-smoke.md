# QA re-edit migration smoke

This note tracks the real-environment migration requirement for the persistent QA-blocked draft repair loop.

## Evidence from real pipeline run

GitHub Actions run `28915165774` ran on `main` at commit `8023a539b493cebb14fdcdbea34330e7f5701abe` after PR #161 was merged.

The pipeline completed and produced one uploaded draft, and the quality report showed the QA gate did not bypass the blocked draft:

- `run_quality_report.status = pass`
- `draft_count = 1`
- `uploaded_draft_count = 1`
- `draft_metadata_count = 1`
- `source_window_overlap_pair_count = 0`
- `qa_gate_bypass_rate = 0.0`
- `qa_review_required_draft_count = 1`
- `qa_blocked_draft_count = 1`

The end-to-end QA re-edit task loop did **not** pass because Supabase rejected the task persistence call:

```text
PGRST204: Could not find the 'approval_blocked_reasons' column of 'reprocess_requests' in the schema cache
```

That means the QA gate blocked the draft correctly, but the required persistent task with `status='qa_blocked'` was not created in `reprocess_requests`.

## Required migration

Apply this migration in the real Supabase project before validating GAP-012 again:

```text
supabase/migrations/20260708_qa_reedit_tasks.sql
```

The real environment must expose these `public.reprocess_requests` columns through Supabase REST/PostgREST:

- `origin`
- `qa_defects`
- `approval_blocked_reasons`
- `attempt_count`
- `max_attempts`
- `last_pipeline_run_id`

It must also include the active-task uniqueness invariant:

```sql
create unique index if not exists reprocess_requests_active_qa_block_idx
  on public.reprocess_requests (draft_name)
  where status in ('qa_blocked', 'pending', 'queued') and draft_name is not null;
```

## Verification SQL

After applying the migration, run this read-only check in the Supabase SQL Editor:

```sql
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'reprocess_requests'
  and column_name in (
    'origin',
    'qa_defects',
    'approval_blocked_reasons',
    'attempt_count',
    'max_attempts',
    'last_pipeline_run_id'
  )
order by column_name;
```

Expected result: six rows.

Then verify the index exists:

```sql
select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'reprocess_requests'
  and indexname = 'reprocess_requests_active_qa_block_idx';
```

Expected result: one row.

## Schema cache requirement

If the SQL checks pass but the pipeline or API still returns `PGRST204`, Supabase REST/PostgREST is still using a stale schema cache. Reload/restart the Supabase API schema cache from the Supabase dashboard, then rerun the preflight.

## Pipeline preflight

`pipeline-run.yml` runs this before expensive video processing:

```bash
python scripts/check_qa_reedit_schema.py
```

This preflight queries `reprocess_requests` with the QA re-edit columns. A missing migration or stale schema cache must fail the pipeline early instead of silently skipping task persistence.

## Pass criteria for GAP-012 validation

A future real pipeline run can close the QA re-edit persistence part only if all are true:

1. `scripts/check_qa_reedit_schema.py` passes in the GitHub Actions environment.
2. A QA-blocked draft writes a `reprocess_requests` row with `status='qa_blocked'` and `origin='qa_gate'`.
3. The row includes non-empty `approval_blocked_reasons` when the QA gate reports reasons.
4. `GET /api/operator/drafts` returns `reedit_task` for that draft.
5. The Review screen surfaces the QA re-edit alert/action.
6. `POST /api/operator/reprocess` promotes the same task to `pending`, increments `attempt_count`, stores `last_pipeline_run_id`, and dispatches `pipeline-run.yml`.
