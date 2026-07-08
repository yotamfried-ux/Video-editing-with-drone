# QA re-edit migration smoke

This note tracks the real-environment migration requirement for the persistent QA-blocked draft repair loop.

## Evidence from real pipeline run before migration

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

## Evidence from real pipeline run after schema preflight

GitHub Actions run `28938769332` ran on `main` at commit `d0c2459941d995532b91fc95c54edff0ec854ca7` after PR #162 was merged.

The `Preflight QA re-edit Supabase schema` step passed. This proves the real Supabase REST/PostgREST schema cache can see the QA re-edit columns, including `approval_blocked_reasons`.

The run again produced a QA-blocked draft and showed no QA bypass:

- `run_quality_report.status = pass`
- `uploaded_draft_count = draft_metadata_count`
- `source_window_overlap_pair_count = 0`
- `qa_gate_bypass_rate = 0.0`
- `qa_review_required_draft_count = 1`
- `qa_blocked_draft_count = 1`

The run logs no longer contained `PGRST204`, `schema cache`, or `QA re-edit task persistence skipped`. However, the diagnostics artifact did not yet contain a direct `reprocess_requests` row snapshot, so the row persistence could not be proven from the artifact alone.

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

## QA re-edit task persistence verifier

`pipeline-run.yml` also runs this after the pipeline and before diagnostics upload:

```bash
python scripts/verify_qa_reedit_tasks.py
```

The verifier reads `/tmp/dtor/pipeline-debug/draft_decision_trace.json`. If the run contains QA-blocked drafts, it queries Supabase for an active `reprocess_requests` row for each blocked draft and writes `/tmp/dtor/pipeline-debug/qa_reedit_task_verification.json`.

For every QA-blocked draft, the verifier requires an active task with:

- `status='qa_blocked'`, `status='pending'`, or `status='queued'`
- `origin='qa_gate'`
- non-empty `notes`
- `qa_defects` when blocking QA defects were present
- non-null `attempt_count`
- non-null `max_attempts`

If a QA-blocked draft has no matching active task, the pipeline fails before uploading the final diagnostics artifact.

## Pass criteria for GAP-012 validation

A future real pipeline run can close the QA re-edit persistence part only if all are true:

1. `scripts/check_qa_reedit_schema.py` passes in the GitHub Actions environment.
2. A QA-blocked draft writes a `reprocess_requests` row with `status='qa_blocked'` and `origin='qa_gate'`.
3. `scripts/verify_qa_reedit_tasks.py` passes and `qa_reedit_task_verification.json` reports `status = pass`.
4. The row includes non-empty `approval_blocked_reasons` when the QA gate reports reasons.
5. `GET /api/operator/drafts` returns `reedit_task` for that draft.
6. The Review screen surfaces the QA re-edit alert/action.
7. `POST /api/operator/reprocess` promotes the same task to `pending`, increments `attempt_count`, stores `last_pipeline_run_id`, and dispatches `pipeline-run.yml`.
