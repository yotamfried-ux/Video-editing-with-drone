import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

// POST /api/operator/pipeline/reset — resets pipeline state and reruns.
// Fires GitHub workflow_dispatch on pipeline-run.yml with reset=true, which:
//   1. Moves all PROCESSED videos back to RAW
//   2. Deletes REVIEW drafts and clears local state
//   3. Reruns the full pipeline on the existing footage
// Optional body: { full_clean: true } — also deletes from APPROVED folder.
// Rate-limited to 3 calls per hour (destructive operation).
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'pipeline-reset', 3, 3600);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      { error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' },
      { status: 503 },
    );
  }

  let fullClean = false;
  try {
    const body = await req.json();
    fullClean = body?.full_clean === true;
  } catch {
    // no body — default to standard reset
  }

  const { data: run, error: insertError } = await supabaseAdmin
    .from('pipeline_runs')
    .insert({
      source: 'reset',
      status: 'queued',
      stage: 'dispatching_reset',
      progress: 0,
      github_event: 'workflow_dispatch:pipeline-run.yml',
      github_run_url: actionsUrl(repo),
      meta: { requested_by: 'operator_app', reset: true, full_clean: fullClean },
    })
    .select('id')
    .single();

  if (insertError || !run) {
    return NextResponse.json(
      { error: insertError?.message ?? 'Could not create reset pipeline run' },
      { status: 500 },
    );
  }

  const res = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ref: 'main',
        inputs: { reset: 'true', full_clean: String(fullClean), pipeline_run_id: run.id },
      }),
    }
  );

  if (res.status !== 204) {
    const text = await res.text();
    const message = `GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}`;
    await supabaseAdmin
      .from('pipeline_runs')
      .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
      .eq('id', run.id);
    return NextResponse.json({ error: message, pipeline_run_id: run.id }, { status: 502 });
  }

  return NextResponse.json({ ok: true, pipeline_run_id: run.id, full_clean: fullClean, github_actions_url: actionsUrl(repo) });
}
