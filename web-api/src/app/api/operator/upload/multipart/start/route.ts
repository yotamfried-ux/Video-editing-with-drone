import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  abortR2MultipartUpload,
  createR2MultipartUpload,
  createR2UploadTarget,
  newBatchId,
  R2_MAX_MULTIPART_PARTS,
  R2_MAX_MULTIPART_PART_SIZE,
  R2_MIN_MULTIPART_PART_SIZE,
  safeBatchId,
  shouldUseR2Storage,
} from '@/lib/r2-storage';
import { attachMultipartSession } from '@/lib/multipart-upload-manifest';
import {
  registerUploadBatch,
  removeSourceUploadsAfterSetupFailure,
  resolveUploadBatchId,
} from '@/lib/upload-batch-manifest';
import {
  createSourceUploadManifests,
  SourceUploadManifestError,
} from '@/lib/source-upload-manifest';

const DEFAULT_PART_SIZE_BYTES = 16 * 1024 * 1024;
const MAX_SOURCE_SIZE_BYTES = 5 * 1024 * 1024 * 1024 * 1024;

function positiveSafeInteger(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-start', 20, 3600);
  if (limited) return limited;

  let body: {
    filename?: string;
    mimeType?: string;
    size?: number;
    batch_id?: string;
    part_size_bytes?: number;
    local_cleanup_required?: boolean;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  if (!shouldUseR2Storage()) {
    return NextResponse.json({ error: 'Multipart upload requires R2 storage' }, { status: 409 });
  }

  const sourceSizeBytes = positiveSafeInteger(body.size);
  if (sourceSizeBytes == null) {
    return NextResponse.json({ error: 'A positive integer source size is required' }, { status: 400 });
  }
  if (sourceSizeBytes > MAX_SOURCE_SIZE_BYTES) {
    return NextResponse.json({ error: 'Source exceeds the 5 TiB multipart object limit' }, { status: 413 });
  }

  const partSizeBytes = body.part_size_bytes == null
    ? DEFAULT_PART_SIZE_BYTES
    : positiveSafeInteger(body.part_size_bytes);
  if (
    partSizeBytes == null
    || partSizeBytes < R2_MIN_MULTIPART_PART_SIZE
    || partSizeBytes > R2_MAX_MULTIPART_PART_SIZE
  ) {
    return NextResponse.json({
      error: `part_size_bytes must be between ${R2_MIN_MULTIPART_PART_SIZE} and ${R2_MAX_MULTIPART_PART_SIZE}`,
    }, { status: 400 });
  }

  const expectedPartCount = Math.ceil(sourceSizeBytes / partSizeBytes);
  if (expectedPartCount < 1 || expectedPartCount > R2_MAX_MULTIPART_PARTS) {
    return NextResponse.json({
      error: `Multipart upload requires ${expectedPartCount} parts; maximum is ${R2_MAX_MULTIPART_PARTS}`,
    }, { status: 413 });
  }

  const requestedBatchId = (body.batch_id ?? '').trim();
  const sanitizedRequestedBatchId = safeBatchId(requestedBatchId);
  if (requestedBatchId && sanitizedRequestedBatchId !== requestedBatchId) {
    return NextResponse.json({ error: 'batch_id contains unsupported characters' }, { status: 400 });
  }

  const sourceFilename = (body.filename ?? '').trim() || `drone_footage_${Date.now()}.mp4`;
  const mimeType = (body.mimeType ?? '').trim() || 'video/mp4';
  let batchId: string;
  try {
    batchId = await resolveUploadBatchId(sanitizedRequestedBatchId) ?? newBatchId();
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Could not resolve upload batch',
    }, { status });
  }

  const target = createR2UploadTarget(sourceFilename, batchId);
  let r2MultipartUploadId: string | null = null;
  let sourceUploadId: string | null = null;

  try {
    r2MultipartUploadId = await createR2MultipartUpload(target.key, mimeType);
    const uploadIds = await createSourceUploadManifests([{
      batchId: target.batch_id,
      storageKey: target.key,
      sourceFilename,
      mimeType,
      sourceSizeBytes,
    }]);
    sourceUploadId = uploadIds.get(target.key) ?? null;
    if (!sourceUploadId) {
      throw new SourceUploadManifestError(`Missing source upload id for ${target.key}`, 503);
    }

    await attachMultipartSession({
      uploadId: sourceUploadId,
      multipartUploadId: r2MultipartUploadId,
      partSizeBytes,
      expectedPartCount,
      localCleanupRequired: body.local_cleanup_required !== false,
    });

    await registerUploadBatch({
      batchId: target.batch_id,
      additionalFileCount: 1,
      sourceKind: 'android_external',
      groupingKind: 'unassigned',
    });

    return NextResponse.json({
      ok: true,
      protocol: 'r2_multipart_v1',
      upload_id: sourceUploadId,
      batch_id: target.batch_id,
      storage_key: target.key,
      filename: target.filename,
      source_filename: sourceFilename,
      mimeType,
      source_size_bytes: sourceSizeBytes,
      part_size_bytes: partSizeBytes,
      expected_part_count: expectedPartCount,
      local_cleanup_required: body.local_cleanup_required !== false,
    });
  } catch (error) {
    if (r2MultipartUploadId) {
      try {
        await abortR2MultipartUpload(target.key, r2MultipartUploadId);
      } catch {
        // Preserve the original setup failure. R2 lifecycle is the final fallback.
      }
    }
    if (sourceUploadId) {
      try {
        await removeSourceUploadsAfterSetupFailure([sourceUploadId]);
      } catch {
        // Preserve the original setup failure; cleanup reconciliation remains visible.
      }
    }
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart upload start failed',
    }, { status });
  }
}
