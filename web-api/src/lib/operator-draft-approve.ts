import { NextRequest, NextResponse } from 'next/server';
import { enforceRateLimit } from '@/lib/ratelimit';
import { getFile, moveFile } from '@/lib/google-drive';
import { moveR2Object, r2Basename, shouldUseR2Storage } from '@/lib/r2-storage';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import { evaluateDraftReviewPolicy } from '@/lib/draft-review-policy';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/deliver.yml`;

type DeliveryRunPatch = { status?: string; stage?: string; error?: string; finished_at?: string };

type ApproveBody = {
  file_id?: string;
  review_required?: boolean;
  qa_review_required?: boolean;
  approval_blocked_reasons?: unknown;
};

export async function approveDraftPost(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'draft-approve', 20, 60);
  if (limited) return limited;

  let body: ApproveBody;
  try { body = await req.json(); } catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }); }
  let fileId = (body.file_id ?? '').trim();
  if (!fileId) return NextResponse.json({ error: 'file_id required' }, { status: 400 });

  const useR2 = shouldUseR2Storage();
  const storageBackend = useR2 ? 'r2' : 'drive';
  let fileName: string | null = null;

  if (useR2) {
    fileName = r2Basename(fileId);
  } else {
    try { fileName = (await getFile(fileId)).name; }
    catch (e) { return NextResponse.json({ error: e instanceof Error ? e.message : 'Drive file lookup failed' }, { status: 502 }); }
  }

  const policy = evaluateDraftReviewPolicy({
    name: fileName,
    review_required: body.review_required,
    qa_review_required: body.qa_review_required,
    approval_blocked_reasons: body.approval_blocked_reasons,
  });
  if (policy.approval_blocked) {
    return NextResponse.json({
      error: 'Draft requires review before approval. Send it to re-edit or clear the QA block first.',
      ...policy,
      storage_move_completed: false,
      delivery_started: false,
    }, { status: 409 });
  }

  if (useR2) {
    try { fileId = await moveR2Object(fileId, 'approved/'); }
    catch (e) { return NextResponse.json({ error: e instanceof Error ? e.message : 'R2 move failed' }, { status: 502 }); }
  } else {
    const reviewFolder = process.env.REVIEW_FOLDER_ID;
    const approvedFolder = process.env.APPROVED_FOLDER_ID;
    if (!reviewFolder || !approvedFolder) return NextResponse.json({ error: 'REVIEW_FOLDER_ID / APPROVED_FOLDER_ID not configured' }, { status: 503 });
    try { await moveFile(fileId, reviewFolder, approvedFolder); }
    catch (e) { return NextResponse.json({ error: e instanceof Error ? e.message : 'Drive move failed' }, { status: 502 }); }
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  const { data: deliveryRun, error: runError } = await supabaseAdmin
    .from('delivery_runs')
    .insert({
      approved_file_id: fileId,
      approved_file_name: fileName,
      source_video: fileName,
      status: 'queued',
      stage: useR2 ? 'approved_moved_to_r2' : 'approved_moved_to_drive',
      github_event: 'reel-approved',
      github_run_url: repo ? actionsUrl(repo) : null,
      meta: { requested_by: 'operator_app', approved_file_name: fileName, storage_backend: storageBackend },
    })
    .select('id')
    .single();

  if (runError || !deliveryRun) {
    console.error('delivery run create failed', runError?.message);
    return NextResponse.json({ error: 'Draft moved to APPROVED, but could not create delivery status record.', storage_move_completed: true }, { status: 500 });
  }

  const runId = deliveryRun.id as string;
  async function updateDeliveryRun(fields: DeliveryRunPatch) {
    const { error } = await supabaseAdmin.from('delivery_runs').update(fields).eq('id', runId);
    if (error) console.error('delivery run update failed', error.message);
    return error;
  }
  async function failDispatch(message: string, status = 502) {
    const error = await updateDeliveryRun({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() });
    return NextResponse.json({ error: error ? `${message} Also failed to persist delivery status.` : message, storage_move_completed: true, delivery_started: false, delivery_run_id: runId }, { status });
  }

  if (!token || !repo) return failDispatch('Delivery dispatch is not configured. Set GITHUB_DISPATCH_TOKEN and GITHUB_REPO in Vercel, then trigger Deliver Preview manually.');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'reel-approved', client_payload: { approved_file_id: fileId, approved_file_name: fileName, delivery_run_id: runId, storage_backend: storageBackend } }),
      signal: controller.signal,
    });
  } catch (e) {
    return failDispatch(e instanceof Error ? e.message : 'Delivery dispatch failed. Trigger Deliver Preview manually.');
  } finally { clearTimeout(timeout); }

  if (res.status !== 204) return failDispatch(githubDispatchError(res.status, await res.text()));
  const updateError = await updateDeliveryRun({ status: 'queued', stage: 'delivery_workflow_dispatched' });
  if (updateError) return NextResponse.json({ error: 'Delivery started, but status update failed.', storage_move_completed: true, delivery_started: true, delivery_run_id: runId }, { status: 202 });
  return NextResponse.json({ ok: true, storage_move_completed: true, delivery_started: true, delivery_run_id: runId, github_actions_url: actionsUrl(repo), storage_backend: storageBackend });
}
