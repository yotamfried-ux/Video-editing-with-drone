import { NextRequest, NextResponse } from 'next/server';

import { githubDispatchError } from '@/lib/github-dispatch-error';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { safeBatchId, shouldUseR2Storage } from '@/lib/r2-storage';
import { supabaseAdmin } from '@/lib/supabase-admin';
import {
  UploadBatchAdmissionError,
  claimVerifiedUploadBatch,
  markUploadBatchDispatched,
  releaseUploadBatchClaim,
} from '@/lib/upload-batch-admission';
import type { PipelineDispatchResponse } from '@/types/operator-contracts';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

async function bestEffortReleaseBatch(batchId: string | null) {
  if (!batchId) return;
  try {
    await releaseUploadBatchClaim(batchId);
  } catch {
    // The original dispatch error remains authoritative. A stuck dispatching
    // batch is visible and can be reconciled without risking duplicate dispatch.
  }
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;

  let body: { batch_id?: string } = {};
  try { body = await req.json(); } catch {}
  const rawBatchId = (body.batch_id ?? '').trim();
  const batchId = safeBatchId(rawBatchId);
  if (rawBatchId && batchId !== rawBatchId) {
    return NextResponse.json({ error: 'batch_id contains unsupported characters' }, { status: 400 });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' }, { status: 503 });

  const r2UploadPath = shouldUseR2Storage();
  if (r2UploadPath && !batchId) {
    return NextResponse.json({ error: 'A verified durable batch_id is required for R2 pipeline runs' }, { status: 409 });
  }

  let admittedBatch: Awaited<ReturnType<typeof claimVerifiedUploadBatch>> | null = null;
  if (r2UploadPath && batchId) {
    try {
      admittedBatch = await claimVerifiedUploadBatch(batchId);
    } catch (error) {
      if (error instanceof UploadBatchAdmissionError) {
        return NextResponse.json({ error: error.message, ...error.details }, { status: error.status });
      }
      return NextResponse.json({ error: error instanceof Error ? error.message : 'Could not verify upload batch' }, { status: 502 });
    }
  }

  const runMeta = {
    requested_by: 'operator_app',
    ...(batchId ? { batch_id: batchId } : {}),
    ...(admittedBatch ? {
      upload_manifest: {
        expected_file_count: admittedBatch.expected_file_count,
        verified_file_count: admittedBatch.verified_file_count,
        grouping_type: admittedBatch.grouping_type,
        session_id: admittedBatch.session_id,
        athlete_id: admittedBatch.athlete_id,
      },
    } : {}),
  };
  const { data: run, error: insertError } = await supabaseAdmin
    .from('pipeline_runs')
    .insert({
      source: 'manual',
      status: 'queued',
      stage: 'dispatching',
      progress: 0,
      github_event: 'new-raw-video',
      github_run_url: actionsUrl(repo),
      input_files: admittedBatch?.input_objects ?? null,
      meta: runMeta,
    })
    .select('id')
    .single();

  if (insertError || !run) {
    await bestEffortReleaseBatch(admittedBatch?.batch_id ?? null);
    return NextResponse.json({ error: insertError?.message ?? 'Could not create pipeline run' }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_type: 'new-raw-video',
        client_payload: {
          pipeline_run_id: run.id,
          source: 'manual',
          ...(batchId ? { batch_id: batchId } : {}),
        },
      }),
      signal: AbortSignal.timeout(8_000),
    });
  } catch (error) {
    const message = error instanceof Error ? `GitHub dispatch request failed: ${error.message}` : 'GitHub dispatch request failed';
    await Promise.all([
      supabaseAdmin
        .from('pipeline_runs')
        .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
        .eq('id', run.id),
      bestEffortReleaseBatch(admittedBatch?.batch_id ?? null),
    ]);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }

  if (res.status !== 204) {
    const message = githubDispatchError(res.status, await res.text());
    await Promise.all([
      supabaseAdmin
        .from('pipeline_runs')
        .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
        .eq('id', run.id),
      bestEffortReleaseBatch(admittedBatch?.batch_id ?? null),
    ]);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }

  let warning: string | undefined;
  if (admittedBatch) {
    try {
      await markUploadBatchDispatched(admittedBatch.batch_id);
    } catch (error) {
      // GitHub already accepted the event. Returning a failure would encourage a
      // duplicate dispatch, so preserve success and surface a reconciliation warning.
      warning = error instanceof Error ? error.message : 'Could not acknowledge dispatched batch state';
    }
  }

  await supabaseAdmin
    .from('pipeline_runs')
    .update({
      status: 'queued',
      stage: 'workflow_dispatched',
      github_run_url: actionsUrl(repo),
      ...(warning ? { error: `Batch acknowledgement warning: ${warning}` } : {}),
    })
    .eq('id', run.id);

  return NextResponse.json<PipelineDispatchResponse>({
    ok: true,
    pipeline_run_id: run.id,
    batch_id: batchId || null,
    github_actions_url: actionsUrl(repo),
    ...(warning ? { warning } : {}),
  });
}
