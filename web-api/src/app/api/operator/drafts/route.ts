import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { listFolder } from '@/lib/google-drive';
import { createR2SignedGetUrl, listR2Prefix, shouldUseR2Storage } from '@/lib/r2-storage';

// GET /api/operator/drafts — list draft reels waiting for approval.
// R2 is the primary backend when configured; Drive remains as fallback.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    if (shouldUseR2Storage()) {
      const files = await listR2Prefix('review/');
      return NextResponse.json({
        drafts: files.map((f) => ({
          id: f.key,
          name: f.name,
          created_at: f.created_at,
          size: f.size,
          watch_url: createR2SignedGetUrl(f.key),
          storage_backend: 'r2',
          storage_key: f.key,
        })),
      });
    }

    const reviewFolder = process.env.REVIEW_FOLDER_ID;
    if (!reviewFolder) {
      return NextResponse.json(
        { error: 'REVIEW_FOLDER_ID not configured' },
        { status: 503 }
      );
    }
    const files = await listFolder(reviewFolder);
    return NextResponse.json({
      drafts: files.map((f) => ({
        id: f.id,
        name: f.name,
        created_at: f.createdTime,
        size: f.size ? Number(f.size) : null,
        watch_url: f.webViewLink ?? null,
        storage_backend: 'drive',
      })),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Storage request failed' },
      { status: 502 }
    );
  }
}
