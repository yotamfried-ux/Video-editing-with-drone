import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

function timeoutAfter(ms: number): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error('GitHub dispatch timed out')), ms);
  });
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' }, { status: 503 });

  const { data: run, error: insertError } = await supabaseAdmin
    .from('pipeline_runs')
    .insert({ source: 'manual', status: 'queued', stage: 'dispatching', progress: 0, github_event: 'new-raw-video', github_run_url: actionsUrl(repo), meta: { requested_by: 'operator_app' } })
    .select('id')
    .single();

  if (insertError || !run) return NextResponse.json({ error: insertError?.message ?? 'Could not create pipeline run' }, { status: 500 });

  async function failDispatch(message: string) {
    await supabaseAdmin.from('pipeline_runs').update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() }).eq('id', run.id);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }

  try {
    const dispatch = fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'new-raw-video', client_payload: { pipeline_run_id: run.id, source: 'manual' } }),
    });
    const res = await Promise.race([dispatch, timeoutAfter(8000)]);
    if (res.status !== 204) return failDispatch(githubDispatchError(res.status, await res.text()));
  } catch (e) {
    return failDispatch(e instanceof Error ? e.message : 'GitHub dispatch request failed');
  }

  await supabaseAdmin.from('pipeline_runs').update({ status: 'queued', stage: 'workflow_dispatched', github_run_url: actionsUrl(repo) }).eq('id', run.id);
  return NextResponse.json({ ok: true, pipeline_run_id: run.id, github_actions_url: actionsUrl(repo) });
}
