import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import { safeBatchId } from '@/lib/r2-storage';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-retry-existing', 3, 3600);
  if (limited) return limited;

  let body: { pipeline_run_id?: string; batch_id?: string } = {};
  try { body = await req.json(); } catch {}
  const pipelineRunId = (body.pipeline_run_id ?? '').trim();
  const requestedBatchId = (body.batch_id ?? '').trim();
  const batchId = safeBatchId(requestedBatchId);
  if (!pipelineRunId || !batchId || batchId !== requestedBatchId) {
    return NextResponse.json({ error: 'Valid pipeline_run_id and batch_id are required' }, { status: 400 });
  }

  const [{ data: run, error: runError }, { data: batch, error: batchError }] = await Promise.all([
    supabaseAdmin.from('pipeline_runs').select('id,status,input_files,meta').eq('id', pipelineRunId).single(),
    supabaseAdmin.from('upload_batches').select('batch_id,state,pipeline_run_id,expected_file_count,input_manifest').eq('batch_id', batchId).single(),
  ]);
  if (runError || !run) return NextResponse.json({ error: 'Pipeline run not found' }, { status: 404 });
  if (batchError || !batch) return NextResponse.json({ error: 'Upload batch not found' }, { status: 404 });

  if (run.status !== 'failed') {
    return NextResponse.json({ error: `Only a failed run can be retried in place (status=${run.status})` }, { status: 409 });
  }
  if (batch.state !== 'failed' || String(batch.pipeline_run_id ?? '') !== pipelineRunId) {
    return NextResponse.json({ error: 'Failed batch is not locked to this exact pipeline run' }, { status: 409 });
  }
  const runManifest = Array.isArray(run.input_files) ? run.input_files : [];
  const batchManifest = Array.isArray(batch.input_manifest) ? batch.input_manifest : [];
  if (!runManifest.length || JSON.stringify(runManifest) !== JSON.stringify(batchManifest)) {
    return NextResponse.json({ error: 'Frozen input manifest does not match the failed batch; retry rejected' }, { status: 409 });
  }
  if (Number(batch.expected_file_count) !== runManifest.length) {
    return NextResponse.json({ error: 'Frozen input count does not match the failed batch; retry rejected' }, { status: 409 });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' }, { status: 503 });

  // Claim the failed run before dispatch. Only one concurrent request can win.
  const { data: claimed, error: claimError } = await supabaseAdmin
    .from('pipeline_runs')
    .update({
      status: 'queued',
      stage: 'dispatching_retry',
      progress: 0,
      error: null,
      finished_at: null,
      github_run_url: actionsUrl(repo),
      meta: { ...(run.meta ?? {}), retry_existing_run: true, reset: false, full_clean: false },
    })
    .eq('id', pipelineRunId)
    .eq('status', 'failed')
    .select('id')
    .maybeSingle();

  if (claimError) {
    return NextResponse.json({ error: 'Could not atomically claim failed run for retry' }, { status: 503 });
  }
  if (!claimed) {
    return NextResponse.json({ error: 'This run was already claimed for retry' }, { status: 409 });
  }

  let dispatchError: string | null = null;
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main', inputs: { reset: 'false', full_clean: 'false', pipeline_run_id: pipelineRunId, batch_id: batchId } }),
    });
    if (res.status !== 204) dispatchError = githubDispatchError(res.status, await res.text());
  } catch (error) {
    // A network timeout is ambiguous: GitHub may have accepted the dispatch.
    // Keep the claim to prevent a second dispatch until an operator reconciles it.
    console.error('Retry dispatch outcome unknown', error);
    return NextResponse.json({ error: 'GitHub dispatch outcome unknown; retry is locked to prevent duplicates', pipeline_run_id: pipelineRunId }, { status: 502 });
  }

  if (dispatchError) {
    const { error: rollbackError } = await supabaseAdmin.from('pipeline_runs')
      .update({ status: 'failed', stage: 'retry_dispatch_failed', error: dispatchError })
      .eq('id', pipelineRunId).eq('status', 'queued').eq('stage', 'dispatching_retry');
    if (rollbackError) {
      return NextResponse.json({ error: 'Dispatch failed and retry state could not be restored; manual reconciliation required' }, { status: 503 });
    }
    return NextResponse.json({ error: dispatchError }, { status: 502 });
  }

  return NextResponse.json({ ok: true, pipeline_run_id: pipelineRunId, batch_id: batchId, github_actions_url: actionsUrl(repo) });
}
