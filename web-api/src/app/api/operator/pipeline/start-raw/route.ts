import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';

// Batchless RAW runs still need a durable identity for progress and terminal status.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GitHub dispatch is not configured' }, { status: 503 });

  const actionsUrl = `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;
  const { data: run, error: insertError } = await supabaseAdmin.from('pipeline_runs').insert({
    source: 'manual',
    status: 'queued',
    stage: 'dispatching',
    progress: 0,
    github_event: 'workflow_dispatch',
    github_run_url: actionsUrl,
    input_files: [],
    meta: { requested_by: 'operator_app', mode: 'simple_raw', batch_id: '' },
  }).select('id').single();
  if (insertError || !run) {
    return NextResponse.json({ error: insertError?.message ?? 'Could not create pipeline run' }, { status: 500 });
  }

  const fail = async (message: string) => {
    const { error } = await supabaseAdmin.from('pipeline_runs').update({
      status: 'dispatch_failed', stage: 'dispatch_failed', error: message,
      finished_at: new Date().toISOString(),
    }).eq('id', run.id);
    if (error) console.error('Failed to finalize RAW dispatch', error);
  };

  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main', inputs: { reset: 'false', full_clean: 'false', batch_id: '', pipeline_run_id: run.id } }),
    });
    if (response.status !== 204) {
      const message = githubDispatchError(response.status, await response.text());
      await fail(message);
      return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
    }
    await supabaseAdmin.from('pipeline_runs').update({ stage: 'workflow_dispatched' }).eq('id', run.id).eq('stage', 'dispatching');
    return NextResponse.json({ ok: true, pipeline_run_id: run.id, github_actions_url: actionsUrl });
  } catch (error) {
    const message = `GitHub dispatch failed: ${error instanceof Error ? error.message : 'unknown error'}`;
    await fail(message);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }
}
