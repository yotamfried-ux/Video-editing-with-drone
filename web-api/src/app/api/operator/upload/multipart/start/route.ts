import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  abortR2MultipartUpload,
  createR2MultipartUpload,
  createR2UploadTarget,
  newBatchId,
  r2Basename,
  R2_MAX_MULTIPART_PARTS,
  R2_MAX_MULTIPART_PART_SIZE,
  R2_MIN_MULTIPART_PART_SIZE,
  safeBatchId,
  shouldUseR2Storage,
} from '@/lib/r2-storage';
import {
  createMultipartSourceManifest,
  findMultipartSessionByClientUploadId,
  getMultipartSession,
  registerMultipartBatchMembership,
  type MultipartSession,
} from '@/lib/multipart-upload-manifest';
import {
  removeSourceUploadsAfterSetupFailure,
  resolveUploadBatchId,
} from '@/lib/upload-batch-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

const DEFAULT_PART_SIZE_BYTES = 16 * 1024 * 1024;
const MAX_SOURCE_SIZE_BYTES = 5 * 1024 * 1024 * 1024 * 1024;
const CLIENT_UPLOAD_ID_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;

function positiveSafeInteger(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function sessionResponse(session: MultipartSession, resumed: boolean) {
  return {
    ok: true,
    protocol: 'r2_multipart_v1' as const,
    upload_id: session.upload_id,
    client_upload_id: session.client_upload_id,
    batch_id: session.batch_id,
    storage_key: session.storage_key,
    filename: r2Basename(session.storage_key),
    source_filename: session.source_filename,
    mimeType: session.mime_type ?? 'video/mp4',
    source_size_bytes: session.source_size_bytes,
    part_size_bytes: session.part_size_bytes,
    expected_part_count: session.expected_part_count,
    completed_part_count: session.completed_part_count,
    upload_status: session.status,
    local_cleanup_required: session.local_cleanup_required,
    local_cleanup_status: session.local_cleanup_status,
    resumed_existing_start: resumed,
  };
}

function assertIdempotentSourceMatches(input: {
  session: MultipartSession;
  clientUploadId: string;
  requestedBatchId: string;
  sourceSizeBytes: number;
  sourceFilename: string;
}): void {
  if (input.session.client_upload_id !== input.clientUploadId) {
    throw new SourceUploadManifestError('Idempotent multipart source identifier mismatch', 409);
  }
  if (input.session.source_size_bytes !== input.sourceSizeBytes) {
    throw new SourceUploadManifestError(
      `Idempotent multipart source size changed: expected ${input.session.source_size_bytes}, got ${input.sourceSizeBytes}`,
      409,
    );
  }
  if (input.session.source_filename !== input.sourceFilename) {
    throw new SourceUploadManifestError('Idempotent multipart source filename changed', 409);
  }
  if (input.requestedBatchId && input.session.batch_id !== input.requestedBatchId) {
    throw new SourceUploadManifestError(
      `Idempotent multipart source belongs to batch ${input.session.batch_id}, not ${input.requestedBatchId}`,
      409,
    );
  }
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-start', 20, 3600);
  if (limited) return limited;

  let body: {
    client_upload_id?: string;
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

  const clientUploadId = (body.client_upload_id ?? '').trim();
  if (!CLIENT_UPLOAD_ID_PATTERN.test(clientUploadId)) {
    return NextResponse.json({
      error: 'client_upload_id must be a stable 16-128 character identifier',
    }, { status: 400 });
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

  try {
    const existing = await findMultipartSessionByClientUploadId(clientUploadId);
    if (existing) {
      assertIdempotentSourceMatches({
        session: existing,
        clientUploadId,
        requestedBatchId: sanitizedRequestedBatchId,
        sourceSizeBytes,
        sourceFilename,
      });
      await registerMultipartBatchMembership(existing.upload_id);
      return NextResponse.json(sessionResponse(existing, true));
    }
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Could not recover multipart start',
    }, { status });
  }

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
  let createdSource = false;

  try {
    r2MultipartUploadId = await createR2MultipartUpload(target.key, mimeType);
    const created = await createMultipartSourceManifest({
      clientUploadId,
      batchId: target.batch_id,
      storageKey: target.key,
      sourceFilename,
      mimeType,
      sourceSizeBytes,
      multipartUploadId: r2MultipartUploadId,
      partSizeBytes,
      expectedPartCount,
      localCleanupRequired: body.local_cleanup_required !== false,
    });
    sourceUploadId = created.uploadId;
    createdSource = created.created;

    if (!createdSource) {
      await abortR2MultipartUpload(target.key, r2MultipartUploadId);
      r2MultipartUploadId = null;
    }

    await registerMultipartBatchMembership(sourceUploadId);
    const session = await getMultipartSession(sourceUploadId);
    assertIdempotentSourceMatches({
      session,
      clientUploadId,
      requestedBatchId: sanitizedRequestedBatchId,
      sourceSizeBytes,
      sourceFilename,
    });
    return NextResponse.json(sessionResponse(session, !createdSource));
  } catch (error) {
    if (r2MultipartUploadId) {
      try {
        await abortR2MultipartUpload(target.key, r2MultipartUploadId);
      } catch {
        // Preserve the original setup failure. R2 lifecycle is the final fallback.
      }
    }
    if (sourceUploadId && createdSource) {
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
