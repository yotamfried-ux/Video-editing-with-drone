import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { moveFile } from '@/lib/google-drive';
import { supabaseAdmin } from '@/lib/supabase-admin';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/deliver.yml`;

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
    return NextResponse.json({ error: runError?.message ?? 'Could not create delivery run', drive_move_completed: true }, { status: 500 });
  }

  async function failDispatch(message: string, status = 502) {
    await supabaseAdmin
      .from('delivery_runs')
      .update({ status: 'dispatch_failed', stage: 'dispatch_failed', error: message, finished_at: new Date().toISOString() })
      .eq('id', deliveryRun.id);
    return NextResponse.json({ error: message, drive_move_completed: true, delivery_started: false, delivery_run_id: deliveryRun.id }, { status });
  }

  if (!token || !repo) return failDispatch('Delivery dispatch is not configured. Trigger Deliver Preview manually.');

  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'reel-approved', client_payload: { approved_file_id: fileId, approved_file_name: fileName, delivery_run_id: deliveryRun.id } }),
    });
  } catch (e) {
    return failDispatch(e instanceof Error ? e.message : 'Delivery dispatch failed. Trigger Deliver Preview manually.');
  }

  if (res.status !== 204) {
    const text = await res.text();
    return failDispatch(`GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}`);
  }

  await supabaseAdmin.from('delivery_runs').update({ status: 'queued', stage: 'delivery_workflow_dispatched' }).eq('id', deliveryRun.id);
  return NextResponse.json({ ok: true, delivery_started: true, delivery_run_id: deliveryRun.id, github_actions_url: actionsUrl(repo) });
}
