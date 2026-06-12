import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { moveFile } from '@/lib/google-drive';

// POST /api/operator/drafts/approve — operator approves a draft from the app.
// Moves the file from REVIEW → APPROVED in Drive, then immediately fires a
// GitHub repository_dispatch (reel-approved) so the Deliver Preview workflow
// starts within seconds — the athlete gets their preview email right away,
// without waiting for the next pipeline run.
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

  // Fire the delivery workflow immediately — best-effort (Drive move already
  // succeeded, so return ok even if the dispatch fails).
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (token && repo) {
    try {
      await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/vnd.github+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ event_type: 'reel-approved' }),
      });
    } catch {
      // Non-fatal — delivery will still happen on the next pipeline run.
    }
  }

  return NextResponse.json({ ok: true });
}
