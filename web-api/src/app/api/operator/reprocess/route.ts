import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;

// GET /api/operator/reprocess — recent reprocess requests (operator app shows
// the queue + status on the Pipeline screen).
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { data, error } = await supabaseAdmin
    .from('reprocess_requests')
    .select('id, draft_name, notes, status, created_at, processed_at')
    .order('created_at', { ascending: false })
    .limit(20);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ requests: data ?? [] });
}

// POST /api/operator/reprocess — operator sends a reel back for re-editing.
//
// Body: { reel_id?: string, draft_name?: string, notes: string }
// Either reel_id (published reel — draft name resolved from reels.source_video)
// or draft_name (draft still in Drive REVIEW) must be provided.
//
// Inserts a reprocess_requests row and immediately dispatches a tracked pipeline
// run so the operator does not need to press Run separately.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'reprocess-write', 10, 60);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      { error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' },
      { status: 503 },
    );
  }

  let body: { reel_id?: string; draft_name?: string; notes?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const notes = (body.notes ?? '').trim().slice(0, 2000);
  let draftName = (body.draft_name ?? '').trim();
  const reelId = (body.reel_id ?? '').trim();

  if (!draftName && reelId) {
    const { data: reel, error } = await supabaseAdmin
      .from('reels')
      .select('source_video')
      .eq('id', reelId)
      .single();
    if (error || !reel) {
      return NextResponse.json({ error: 'Reel not found' }, { status: 404 });
    }
    draftName = reel.source_video ?? '';
  }

  if (!draftName) {
    return NextResponse.json(
      { error: 'reel_id or draft_name required' },
      { status: 400 },
    );
  }

  const { data: request, error: requestError } = await supabaseAdmin
    .from('reprocess_requests')
    .insert({ reel_id: reelId || null, draft_name: draftName, notes })
    .select('id')
    .single();

  if (requestError || !request) {
    return NextResponse.json(
      { error: requestError?.message ?? 'Could not create reprocess request' },
      { status: 500 },
    );
  }

  const { data: run, error: runError } = await supabaseAdmin
    .from('pipeline_runs')
    .insert({
      source: 'reprocess',
      status: 'queued',
      stage: 'dispatching_reprocess',
      progress: 0,
      github_event: 'workflow_dispatch:pipeline-run.yml',
      github_run_url: actionsUrl(repo),
      meta: {
        requested_by: 'operator_app',
        reprocess_request_id: request.id,
        draft_name: draftName,
        reel_id: reelId || null,
      },
    })
    .select('id')
    .single();

  if (runError || !run) {
    return NextResponse.json(
      { error: runError?.message ?? 'Could not create reprocess pipeline run', request_id: request.id },
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
        inputs: { reset: 'false', pipeline_run_id: run.id },
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
    return NextResponse.json({ error: message, request_id: request.id, pipeline_run_id: run.id }, { status: 502 });
  }

  return NextResponse.json({
    ok: true,
    request_id: request.id,
    pipeline_run_id: run.id,
    github_actions_url: actionsUrl(repo),
  });
}
