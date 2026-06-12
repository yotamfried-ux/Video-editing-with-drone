import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { listFolder } from '@/lib/google-drive';

// GET /api/operator/drafts — list draft reels waiting in the Drive REVIEW
// folder so the operator can approve or send them back from the app.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const reviewFolder = process.env.REVIEW_FOLDER_ID;
  if (!reviewFolder) {
    return NextResponse.json(
      { error: 'REVIEW_FOLDER_ID not configured' },
      { status: 503 }
    );
  }

  try {
    const files = await listFolder(reviewFolder);
    return NextResponse.json({
      drafts: files.map((f) => ({
        id: f.id,
        name: f.name,
        created_at: f.createdTime,
        size: f.size ? Number(f.size) : null,
        watch_url: f.webViewLink ?? null,
      })),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Drive request failed' },
      { status: 502 }
    );
  }
}
