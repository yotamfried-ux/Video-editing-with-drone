import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { moveFile } from '@/lib/google-drive';
import { supabaseAdmin } from '@/lib/supabase-admin';

export const dynamic = 'force-dynamic';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/deliver.yml`;

type DeliveryRunPatch = {
  status?: string;
  stage?: string;
  error?: string;
  finished_at?: string;
};

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'draft-approve', 20, 60);
  if (limited) return limited;

  const reviewFolder = process.env.REVIEW_FOLDER_ID;
  const approvedFolder = process.env.APPROVED_FOLDER_ID;
  if (!reviewFolder || !approvedFolder) {
    return NextResponse.json({ error: 'REVIEW_FOLDER_ID / APPROVED_FOLDER_ID not configured' }, { status: 503 });
  }

  let body: { file_id?: string; file_name?: string };
  try { body = await req.json(); } catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }); }
  const fileId = (body.file_id ?? '').trim();
  const fileName = (body.file_name ?? '').trim() || null;
  if (!fileId) return NextResponse.json({ error: 'file_id required' }, { status: 400 });

  try {
    await moveFile(fileId, reviewFolder, approvedFolder);
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : 'Drive move failed' }, { status: 502 });
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
      stage: 'approved_moved_to_drive',
      github_event: 'reel-approved',
      github_run_url: repo ? actionsUrl(repo) : null,
      meta: { requested_by: 'operator_app' },
    })
    .select('id')
    .single();

  if (runError || !deliveryRun) {
    console.error('delivery run create failed', runError?.message);
    return NextResponse.json({ error: 'Draft moved to APPROVED, but could not create delivery status record.', drive_move_completed: true }, { status: 500 });
  }

  async function updateDeliveryRun(fields: DeliveryRunPatch) {
    const { error } = await supabaseAdmin.from('delivery_runs').update(fields).eq('id', deliveryRun.id);
    if (error) console.error('delivery run update failed', error.message);
    return error;
  }

  async function failDispatch(message: string, status = 502) {
    const error = await updateDeliveryRun({
      status: 'dispatch_failed',
      stage: 'dispatch_failed',
      error: message,
      finished_at: new Date().toISOString(),
    });
    return NextResponse.json(
      {
        error: error ? `${message} Also failed to persist delivery status.` : message,
        drive_move_completed: true,
        delivery_started: false,
        delivery_run_id: deliveryRun.id,
      },
      { status },
    );
  }

  if (!token || !repo) return failDispatch('Delivery dispatch is not configured. Trigger Deliver Preview manually.');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'reel-approved', client_payload: { approved_file_id: fileId, approved_file_name: fileName, delivery_run_id: deliveryRun.id } }),
      signal: controller.signal,
    });
  } catch (e) {
    return failDispatch(e instanceof Error ? e.message : 'Delivery dispatch failed. Trigger Deliver Preview manually.');
  } finally {
    clearTimeout(timeout);
  }

  if (res.status !== 204) {
    const text = await res.text();
    return failDispatch(`GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}`);
  }

  const updateError = await updateDeliveryRun({ status: 'queued', stage: 'delivery_workflow_dispatched' });
  if (updateError) {
    return NextResponse.json(
      { error: 'Delivery started, but status update failed.', drive_move_completed: true, delivery_started: true, delivery_run_id: deliveryRun.id },
      { status: 202 },
    );
  }

  return NextResponse.json({ ok: true, delivery_started: true, delivery_run_id: deliveryRun.id, github_actions_url: actionsUrl(repo) });
}
