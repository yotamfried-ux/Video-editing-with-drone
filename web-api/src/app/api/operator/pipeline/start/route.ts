import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import { safeBatchId } from '@/lib/r2-storage';
import {
  assertUploadBatchReady,
  markUploadBatchRunning,
  releaseUploadBatchAfterDispatchFailure,
} from '@/lib/upload-batch-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';
import type { PipelineDispatchResponse } from '@/types/operator-contracts';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

async function failDispatch(input: {
  batchId: string;
  pipelineRunId: string;
  message: string;
}): Promise<void> {
  await supabaseAdmin
    .from('pipeline_runs')
    .update({
      status: 'dispatch_failed',
      stage: 'dispatch_failed',
      error: input.message,
      finished_at: new Date().toISOString(),
    })
    .eq('id', input.pipelineRunId);

  try {
    await releaseUploadBatchAfterDispatchFailure(input.batchId, input.pipelineRunId);
  } catch (error) {
    console.error('Could not release upload batch after dispatch failure', error);
  }
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;

  let body: { batch_id?: string } = {};
  try { body = await req.json(); } catch {}
  const requestedBatchId = (body.batch_id ?? '').trim();
  const batchId = safeBatchId(requestedBatchId);
  if (!requestedBatchId) {
    return NextResponse.json({ error: 'A durable verified batch_id is required' }, { status: 400 });
  }
  if (!batchId || batchId !== requestedBatchId) {
    return NextResponse.json({ error: 'batch_id contains unsupported characters' }, { status: 400 });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' }, { status: 503 });

  let readyBatch: Awaited<ReturnType<typeof assertUploadBatchReady>>;
  try {
    readyBatch = await assertUploadBatchReady(batchId);
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Upload batch readiness check failed',
      batch_id: batchId,
    }, { status });
  }

  const runMeta = {
    requested_by: 'operator_app',
    batch_id: batchId,
    expected_file_count: readyBatch.expectedFileCount,
    input_manifest_frozen: true,
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
      input_files: readyBatch.inputManifest,
      meta: runMeta,
    })
    .select('id')
    .single();

  if (insertError || !run) {
    return NextResponse.json({ error: insertError?.message ?? 'Could not create pipeline run' }, { status: 500 });
  }

  try {
    await markUploadBatchRunning(batchId, run.id);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Could not lock upload batch';
    await supabaseAdmin
      .from('pipeline_runs')
      .update({
        status: 'dispatch_failed',
        stage: 'dispatch_failed',
        error: message,
        finished_at: new Date().toISOString(),
      })
      .eq('id', run.id);
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({ error: message, pipeline_run_id: run.id, batch_id: batchId }, { status });
  }

  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'new-raw-video',
        client_payload: {
          pipeline_run_id: run.id,
          source: 'manual',
          batch_id: batchId,
          expected_file_count: readyBatch.expectedFileCount,
        },
      }),
    });
  } catch (error) {
    const message = `GitHub dispatch network error: ${error instanceof Error ? error.message : 'unknown error'}`;
    await failDispatch({ batchId, pipelineRunId: run.id, message });
    return NextResponse.json({ error: message, pipeline_run_id: run.id, batch_id: batchId }, { status: 502 });
  }

  if (res.status !== 204) {
    const message = githubDispatchError(res.status, await res.text());
    await failDispatch({ batchId, pipelineRunId: run.id, message });
    return NextResponse.json({ error: message, pipeline_run_id: run.id, batch_id: batchId }, { status: 502 });
  }

  await supabaseAdmin
    .from('pipeline_runs')
    .update({
      status: 'queued',
      stage: 'workflow_dispatched',
      github_run_url: actionsUrl(repo),
    })
    .eq('id', run.id);

  return NextResponse.json<PipelineDispatchResponse>({
    ok: true,
    pipeline_run_id: run.id,
    batch_id: batchId,
    github_actions_url: actionsUrl(repo),
  });
}
