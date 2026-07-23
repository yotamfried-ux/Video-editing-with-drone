import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { recordLocalCleanup } from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

const ALLOWED_STATUSES = new Set(['not_required', 'confirmed', 'failed']);

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-cleanup', 60, 3600);
  if (limited) return limited;

  let body: {
    upload_id?: string;
    cleanup_status?: string;
    artifact_count?: number;
    reclaimed_bytes?: number;
    source_preserved?: boolean;
    error?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  const cleanupStatus = (body.cleanup_status ?? '').trim().toLowerCase();
  const artifactCount = Number(body.artifact_count);
  const reclaimedBytes = Number(body.reclaimed_bytes);

  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });
  if (!ALLOWED_STATUSES.has(cleanupStatus)) {
    return NextResponse.json({ error: 'cleanup_status must be not_required, confirmed, or failed' }, { status: 400 });
  }
  if (!Number.isSafeInteger(artifactCount) || artifactCount < 0) {
    return NextResponse.json({ error: 'artifact_count must be a non-negative safe integer' }, { status: 400 });
  }
  if (!Number.isSafeInteger(reclaimedBytes) || reclaimedBytes < 0) {
    return NextResponse.json({ error: 'reclaimed_bytes must be a non-negative safe integer' }, { status: 400 });
  }
  if (body.source_preserved !== true) {
    return NextResponse.json({
      error: 'Cleanup confirmation requires proof that the selected SD/USB source was preserved',
    }, { status: 409 });
  }
  if (cleanupStatus === 'failed' && !(body.error ?? '').trim()) {
    return NextResponse.json({ error: 'Cleanup failure requires an error' }, { status: 400 });
  }

  try {
    const result = await recordLocalCleanup({
      uploadId,
      status: cleanupStatus as 'not_required' | 'confirmed' | 'failed',
      artifactCount,
      reclaimedBytes,
      sourcePreserved: true,
      error: (body.error ?? '').trim() || null,
    });
    return NextResponse.json({ ok: true, ...result });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Local cleanup evidence failed',
    }, { status });
  }
}
