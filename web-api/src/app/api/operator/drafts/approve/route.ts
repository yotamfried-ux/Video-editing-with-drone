import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { moveFile } from '@/lib/google-drive';

const actionsUrl = (repo: string) => `https://github.com/${repo}/actions/workflows/deliver.yml`;

// POST /api/operator/drafts/approve — operator approves a draft from the app.
// Moves the file from REVIEW → APPROVED, then immediately fires a GitHub
// repository_dispatch (reel-approved) so the Deliver Preview workflow starts
// within seconds. Dispatch failure is returned as an API error instead of being
// silently swallowed, because otherwise the app can claim delivery started when
// no GitHub Actions run was created.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'draft-approve', 20, 60);
  if (limited) return limited;

  const reviewFolder = process.env.REVIEW_FOLDER_ID;
  const approvedFolder = process.env.APPROVED_FOLDER_ID;
  if (!reviewFolder || !approvedFolder) {
    return NextResponse.json(
      { error: 'REVIEW_FOLDER_ID / APPROVED_FOLDER_ID not configured' },
      { status: 503 }
    );
  }

  let body: { file_id?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const fileId = (body.file_id ?? '').trim();
  if (!fileId) {
    return NextResponse.json({ error: 'file_id required' }, { status: 400 });
  }

  try {
    await moveFile(fileId, reviewFolder, approvedFolder);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Drive move failed' },
      { status: 502 }
    );
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      {
        error: 'Draft moved to APPROVED, but GITHUB_DISPATCH_TOKEN / GITHUB_REPO is not configured. Trigger Deliver Preview manually.',
        drive_move_completed: true,
        delivery_started: false,
      },
      { status: 502 }
    );
  }

  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ event_type: 'reel-approved', client_payload: { approved_file_id: fileId } }),
    });
  } catch (e) {
    return NextResponse.json(
      {
        error: e instanceof Error ? e.message : 'Draft moved to APPROVED, but delivery dispatch failed. Trigger Deliver Preview manually.',
        drive_move_completed: true,
        delivery_started: false,
      },
      { status: 502 }
    );
  }

  if (res.status !== 204) {
    const text = await res.text();
    return NextResponse.json(
      {
        error: `Draft moved to APPROVED, but GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}`,
        drive_move_completed: true,
        delivery_started: false,
      },
      { status: 502 }
    );
  }

  return NextResponse.json({ ok: true, delivery_started: true, github_actions_url: actionsUrl(repo) });
}
