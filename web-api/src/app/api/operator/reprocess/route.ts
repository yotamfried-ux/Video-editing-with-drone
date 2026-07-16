import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import type { ReprocessListResponse, ReprocessRow, ReprocessSubmitResponse } from '@/types/operator-contracts';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;
const ACTIVE_QA_STATUSES = ['qa_blocked', 'pending', 'queued'];
const IN_FLIGHT_QA_STATUSES = ['pending', 'queued'];

function mergeNotes(existing: string | null | undefined, submitted: string): string {
  const current = (existing ?? '').trim();
  const next = submitted.trim();
  if (!current) return next;
  if (!next || current.includes(next)) return current;
  return `${current}\n\nOperator notes:\n${next}`.slice(0, 2000);
}

async function findActiveQaTask(draftName: string) {
  const { data, error } = await supabaseAdmin
    .from('reprocess_requests')
    .select('id, draft_name, notes, status, attempt_count, max_attempts, last_pipeline_run_id')
    .eq('draft_name', draftName)
    .in('status', ACTIVE_QA_STATUSES)
    .order('created_at', { ascending: false })
    .limit(1);
  if (error) throw error;
  return data?.[0] ?? null;
}

function inFlightResponse(task: any, draftName: string) {
  return NextResponse.json(
    {
      error: `A re-edit is already ${task.status} for ${draftName}. Wait for the current pipeline run to finish before sending it again.`,
      request_id: task.id,
      pipeline_run_id: task.last_pipeline_run_id ?? null,
      reedit_status: task.status,
    },
    { status: 409 },
  );
}

// GET /api/operator/reprocess — recent reprocess requests (operator app shows
// the queue + status on the Pipeline screen and Review screen can surface
// qa_blocked tasks next to the draft that needs repair).
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const { data, error } = await supabaseAdmin
    .from('reprocess_requests')
    .select('id, draft_name, notes, status, origin, qa_defects, approval_blocked_reasons, attempt_count, max_attempts, last_pipeline_run_id, created_at, processed_at')
    .order('created_at', { ascending: false })
    .limit(20);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json<ReprocessListResponse>({ requests: (data ?? []) as ReprocessRow[] });
}

// POST /api/operator/reprocess — operator sends a reel back for re-editing.
//
// Body: { reel_id?: string, draft_name?: string, reprocess_request_id?: string, notes: string }
// Either an existing qa_blocked reprocess_request_id, reel_id, or draft_name must
// be provided. For QA-blocked drafts this promotes the existing task to pending
// and dispatches a tracked run with the QA notes.
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

  let body: { reel_id?: string; draft_name?: string; reprocess_request_id?: string; notes?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const submittedNotes = (body.notes ?? '').trim().slice(0, 2000);
  let draftName = (body.draft_name ?? '').trim();
  const reelId = (body.reel_id ?? '').trim();
  const reprocessRequestId = (body.reprocess_request_id ?? '').trim();
  let existingTask: any = null;

  if (reprocessRequestId) {
    const { data, error } = await supabaseAdmin
      .from('reprocess_requests')
      .select('id, draft_name, notes, status, attempt_count, max_attempts, last_pipeline_run_id')
      .eq('id', reprocessRequestId)
      .single();
    if (error || !data) {
      return NextResponse.json({ error: 'Re-edit task not found' }, { status: 404 });
    }
    existingTask = data;
    draftName = draftName || data.draft_name || '';
  }

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
      { error: 'reprocess_request_id, reel_id, or draft_name required' },
      { status: 400 },
    );
  }

  if (!existingTask) {
    try {
      existingTask = await findActiveQaTask(draftName);
    } catch (error) {
      return NextResponse.json(
        { error: error instanceof Error ? error.message : 'Could not read re-edit task' },
        { status: 500 },
      );
    }
  }

  if (existingTask && IN_FLIGHT_QA_STATUSES.includes(existingTask.status)) {
    return inFlightResponse(existingTask, draftName);
  }

  const currentAttempts = Number(existingTask?.attempt_count ?? 0);
  const maxAttempts = Number(existingTask?.max_attempts ?? 3);
  if (existingTask && currentAttempts >= maxAttempts) {
    await supabaseAdmin
      .from('reprocess_requests')
      .update({ status: 'failed_max_attempts', processed_at: new Date().toISOString() })
      .eq('id', existingTask.id);
    return NextResponse.json(
      { error: `Maximum re-edit attempts reached for ${draftName}. Manually reject or review this draft.`, request_id: existingTask.id },
      { status: 409 },
    );
  }

  let requestId = existingTask?.id as string | undefined;
  const notes = mergeNotes(existingTask?.notes, submittedNotes);
  if (existingTask) {
    const { data: updated, error: updateError } = await supabaseAdmin
      .from('reprocess_requests')
      .update({
        status: 'pending',
        notes,
        attempt_count: currentAttempts + 1,
        processed_at: null,
      })
      .eq('id', existingTask.id)
      .eq('status', 'qa_blocked')
      .select('id')
      .single();
    if (updateError || !updated) {
      return NextResponse.json(
        { error: updateError?.message ?? 'Could not update re-edit task' },
        { status: 500 },
      );
    }
    requestId = updated.id;
  } else {
    const { data: request, error: requestError } = await supabaseAdmin
      .from('reprocess_requests')
      .insert({
        reel_id: reelId || null,
        draft_name: draftName,
        notes,
        status: 'pending',
        origin: 'operator',
        attempt_count: 1,
        max_attempts: 3,
      })
      .select('id')
      .single();

    if (requestError || !request) {
      return NextResponse.json(
        { error: requestError?.message ?? 'Could not create reprocess request' },
        { status: 500 },
      );
    }
    requestId = request.id;
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
        reprocess_request_id: requestId,
        draft_name: draftName,
        reel_id: reelId || null,
        qa_reedit_task: Boolean(existingTask),
      },
    })
    .select('id')
    .single();

  if (runError || !run) {
    return NextResponse.json(
      { error: runError?.message ?? 'Could not create reprocess pipeline run', request_id: requestId },
      { status: 500 },
    );
  }

  await supabaseAdmin
    .from('reprocess_requests')
    .update({ last_pipeline_run_id: run.id })
    .eq('id', requestId);

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
    const message = githubDispatchError(res.status, await res.text());
    await supabaseAdmin
      .from('pipeline_runs')
      .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
      .eq('id', run.id);
    return NextResponse.json({ error: message, request_id: requestId, pipeline_run_id: run.id }, { status: 502 });
  }

  return NextResponse.json<ReprocessSubmitResponse>({
    ok: true,
    request_id: requestId as string,
    pipeline_run_id: run.id,
    github_actions_url: actionsUrl(repo),
  });
}
