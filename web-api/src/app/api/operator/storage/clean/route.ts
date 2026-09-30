import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  advanceCleanup, CLEANUP_CONFIRMATION, CleanupError, getLatestRun, isRunId, previewCleanup,
} from '@/lib/video-storage-cleanup-runtime';
import type { StorageCleanPreviewResponse, StorageCleanResponse } from '@/types/operator-contracts';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

const errorResponse = (error: unknown) => {
  if (error instanceof CleanupError) {
    return NextResponse.json({ error: error.message, code: error.code, ...(error.runId ? { run_id: error.runId } : {}) }, { status: error.status });
  }
  return NextResponse.json({ error: 'Video storage cleanup service error' }, { status: 502 });
};

// GET — read-only preview (inventory + active DB state). Never mutates.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  try {
    const [preview, latest] = await Promise.all([previewCleanup(), getLatestRun()]);
    return NextResponse.json<StorageCleanPreviewResponse>({ ...preview, latest_run: latest });
  } catch (error) {
    return errorResponse(error);
  }
}

// POST — start (confirmation required) or continue (run_id) a resumable cleanup run.
// The client cannot choose buckets, prefixes or keys: scope is fixed server-side.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'operator-storage-clean', 300, 3600);
  if (limited) return limited;

  let body: { confirmation?: unknown; run_id?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const runId = body.run_id;
  if (runId !== undefined && !isRunId(runId)) return NextResponse.json({ error: 'Invalid run_id' }, { status: 400 });
  if (runId === undefined && body.confirmation !== CLEANUP_CONFIRMATION) {
    return NextResponse.json({ error: `confirmation must equal ${CLEANUP_CONFIRMATION}` }, { status: 400 });
  }
  try {
    return NextResponse.json<StorageCleanResponse>(await advanceCleanup({ runId: runId as string | undefined }));
  } catch (error) {
    return errorResponse(error);
  }
}
