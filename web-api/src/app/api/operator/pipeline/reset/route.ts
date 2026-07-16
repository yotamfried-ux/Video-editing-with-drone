import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import { safeBatchId } from '@/lib/r2-storage';
import type { PipelineResetResponse } from '@/types/operator-contracts';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'pipeline-reset', 3, 3600);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' }, { status: 503 });
  }

  let fullClean = false;
  let batchId = '';
  try {
    const body = await req.json();
    fullClean = body?.full_clean === true;
    batchId = safeBatchId(body?.batch_id);
  } catch {}

  const meta = { requested_by: 'operator_app', reset: true, full_clean: fullClean, ...(batchId ? { batch_id: batchId } : {}) };
  const { data: run, error: insertError } = await supabaseAdmin
    .from('pipeline_runs')
    .insert({
      source: 'reset',
      status: 'queued',
      stage: 'dispatching_reset',
      progress: 0,
      github_event: 'workflow_dispatch:pipeline-run.yml',
      github_run_url: actionsUrl(repo),
      meta,
    })
    .select('id')
    .single();

  if (insertError || !run) {
    return NextResponse.json({ error: insertError?.message ?? 'Could not create reset pipeline run' }, { status: 500 });
  }

  const res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ref: 'main',
      inputs: { reset: 'true', full_clean: String(fullClean), pipeline_run_id: run.id, batch_id: batchId },
    }),
  });

  if (res.status !== 204) {
    const message = githubDispatchError(res.status, await res.text());
    await supabaseAdmin
      .from('pipeline_runs')
      .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
      .eq('id', run.id);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }

  return NextResponse.json<PipelineResetResponse>({ ok: true, pipeline_run_id: run.id, batch_id: batchId || null, full_clean: fullClean, github_actions_url: actionsUrl(repo) });
}
