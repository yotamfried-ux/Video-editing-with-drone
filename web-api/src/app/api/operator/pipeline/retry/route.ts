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

  const res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: 'main', inputs: { reset: 'false', full_clean: 'false', pipeline_run_id: pipelineRunId, batch_id: batchId } }),
  });
  if (res.status !== 204) {
    return NextResponse.json({ error: githubDispatchError(res.status, await res.text()) }, { status: 502 });
  }

  await supabaseAdmin.from('pipeline_runs').update({
    status: 'queued', stage: 'workflow_dispatched_retry', progress: 0, error: null, finished_at: null,
    github_run_url: actionsUrl(repo),
    meta: { ...(run.meta ?? {}), retry_existing_run: true, reset: false, full_clean: false },
  }).eq('id', pipelineRunId).eq('status', 'failed');

  return NextResponse.json({ ok: true, pipeline_run_id: pipelineRunId, batch_id: batchId, github_actions_url: actionsUrl(repo) });
}
