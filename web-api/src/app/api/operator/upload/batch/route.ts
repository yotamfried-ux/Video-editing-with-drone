import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { newBatchId, safeBatchId } from '@/lib/r2-storage';
import { registerUploadBatch } from '@/lib/upload-batch-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

const SOURCE_KINDS = new Set(['operator', 'android_external', 'gallery', 'api']);
const GROUPING_KINDS = new Set(['unassigned', 'one_athlete', 'session_multiple_athletes', 'other']);

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-upload-batch', 30, 3600);
  if (limited) return limited;

  let body: {
    batch_id?: string;
    additional_file_count?: number;
    source_kind?: string;
    grouping_kind?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const additionalFileCount = Number(body.additional_file_count);
  if (!Number.isInteger(additionalFileCount) || additionalFileCount < 1 || additionalFileCount > 1000) {
    return NextResponse.json({ error: 'additional_file_count must be an integer from 1 to 1000' }, { status: 400 });
  }

  const requestedBatchId = (body.batch_id ?? '').trim();
  const normalizedBatchId = safeBatchId(requestedBatchId);
  if (requestedBatchId && normalizedBatchId !== requestedBatchId) {
    return NextResponse.json({ error: 'batch_id contains unsupported characters' }, { status: 400 });
  }
  const batchId = normalizedBatchId || newBatchId();

  const sourceKind = (body.source_kind ?? 'operator').trim().toLowerCase();
  const groupingKind = (body.grouping_kind ?? 'unassigned').trim().toLowerCase();
  if (!SOURCE_KINDS.has(sourceKind)) {
    return NextResponse.json({ error: 'Unsupported source_kind' }, { status: 400 });
  }
  if (!GROUPING_KINDS.has(groupingKind)) {
    return NextResponse.json({ error: 'Unsupported grouping_kind' }, { status: 400 });
  }

  try {
    const batch = await registerUploadBatch({
      batchId,
      additionalFileCount,
      sourceKind: sourceKind as 'operator' | 'android_external' | 'gallery' | 'api',
      groupingKind: groupingKind as 'unassigned' | 'one_athlete' | 'session_multiple_athletes' | 'other',
    });
    return NextResponse.json({ ok: true, ...batch });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Upload batch registration failed',
    }, { status });
  }
}
