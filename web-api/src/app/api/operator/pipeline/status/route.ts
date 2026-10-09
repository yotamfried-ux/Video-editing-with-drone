import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { supabaseAdmin } from '@/lib/supabase-admin';
import type { PipelineRunRow, PipelineStatusResponse, PipelineStatusRow } from '@/types/operator-contracts';

export const dynamic = 'force-dynamic';

const STALE_GLOBAL_AFTER_MS = 15 * 60 * 1000;
const TERMINAL_DRIFT_MS = 30 * 1000;
const TERMINAL_RUN_STATUSES = new Set(['succeeded', 'failed', 'no_input', 'dispatch_failed']);
const GLOBAL_TERMINAL_STAGES = new Set(['done', 'failed', 'no_input']);

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

function isTerminalRun(run: PipelineRunRow | null): boolean {
  return Boolean(run && TERMINAL_RUN_STATUSES.has(run.status));
}

function isGlobalTerminal(status: PipelineStatusRow | null): boolean {
  return Boolean(
    status &&
      (GLOBAL_TERMINAL_STAGES.has(status.stage) || Number(status.progress) >= 1)
  );
}

function isGlobalLiveStale(
  status: PipelineStatusRow | null,
  latestRun: PipelineRunRow | null,
  now = Date.now(),
): boolean {
  if (!status || !isTerminalRun(latestRun)) return false;

  const statusUpdatedAt = parseTime(status.updated_at);
  const latestTerminalAt = parseTime(
    latestRun?.finished_at ?? latestRun?.updated_at ?? latestRun?.queued_at,
  );

  if (!statusUpdatedAt || !latestTerminalAt) return false;

  if (latestTerminalAt > statusUpdatedAt + TERMINAL_DRIFT_MS) {
    return true;
  }

  return now - statusUpdatedAt > STALE_GLOBAL_AFTER_MS && !isGlobalTerminal(status);
}

function buildGlobalStaleReason(latestRun: PipelineRunRow | null): string | null {
  if (!latestRun) return null;

  const runLabel = latestRun.id.slice(0, 8);
  if (latestRun.status === 'succeeded') {
    return `Global live signal is stale; latest run ${runLabel} finished successfully.`;
  }
  if (latestRun.status === 'no_input') {
    return `Global live signal is stale; latest run ${runLabel} finished with no new input.`;
  }

  return `Global live signal is stale; latest run ${runLabel} finished with status ${latestRun.status}.`;
}

export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { data: status, error: statusError } = await supabaseAdmin
    .from('pipeline_status')
    .select('stage, progress, meta, updated_at')
    .eq('id', 1)
    .maybeSingle();

  if (statusError) {
    return NextResponse.json({ error: statusError.message }, { status: 500 });
  }

  const { data: latestRuns, error: runsError } = await supabaseAdmin
    .from('pipeline_runs')
    .select(
      'id, source, status, stage, progress, github_run_url, input_files, output_drafts, error, meta, queued_at, started_at, finished_at, updated_at'
    )
    .order('queued_at', { ascending: false })
    .limit(1);

  if (runsError) {
    return NextResponse.json({ error: runsError.message }, { status: 500 });
  }

  const latestRun = (latestRuns?.[0] ?? null) as PipelineRunRow | null;
  // Legacy pipeline runs may omit meta.batch_id even though the frozen batch is
  // linked by upload_batches.pipeline_run_id. Resolve that authoritative link
  // without changing the run or the frozen inputs.
  if (latestRun?.status === 'failed' && !String(latestRun.meta?.batch_id ?? '').trim()) {
    const { data: linkedBatches, error: batchError } = await supabaseAdmin
      .from('upload_batches')
      .select('batch_id, state, expected_file_count, actual_file_count, verified_file_count')
      .eq('pipeline_run_id', latestRun.id)
      .eq('state', 'failed')
      .limit(2);

    if (batchError) {
      return NextResponse.json({ error: 'Could not verify failed run batch' }, { status: 503 });
    }

    const batch = linkedBatches?.length === 1 ? linkedBatches[0] : null;
    if (
      batch &&
      batch.expected_file_count > 0 &&
      batch.actual_file_count === batch.expected_file_count &&
      batch.verified_file_count === batch.expected_file_count
    ) {
      latestRun.meta = { ...(latestRun.meta ?? {}), batch_id: batch.batch_id };
    }
  }

  const globalLiveStale = isGlobalLiveStale((status ?? null) as PipelineStatusRow | null, latestRun);

  return NextResponse.json<PipelineStatusResponse>({
    status: status ?? null,
    latest_run: latestRun,
    global_live_stale: globalLiveStale,
    global_live_stale_reason: globalLiveStale ? buildGlobalStaleReason(latestRun) : null,
  });
}
