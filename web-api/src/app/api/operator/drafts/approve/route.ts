import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { moveFile } from '@/lib/google-drive';

// POST /api/operator/drafts/approve — operator approves a draft from the app.
// Moves the file from the Drive REVIEW folder to APPROVED; the delivery
// pipeline picks it up from there on its next run (preview → payment →
// publish), exactly as if it had been moved manually in Drive.
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
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Drive move failed' },
      { status: 502 }
    );
  }
}
