import { getSportReelSourceReader } from '../../../../modules/sportreel-source-reader/src/SportReelSourceReaderModule';
import { operatorFetch } from './operatorApi';
import { withRetry } from './uploadQueue';
import {
  activeMultipartTemporaryUris,
  findDurableMultipartUpload,
  getOrCreatePendingMultipartStart,
  removeDurableMultipartUpload,
  removePendingMultipartStart,
  upsertDurableMultipartUpload,
  type DurableMultipartPart,
  type DurableMultipartUpload,
} from './multipartUploadLedger';
import {
  cleanupVerifiedUploadArtifacts,
  sweepStaleSportReelUploadArtifacts,
} from './uploadLocalCleanup';

const MAX_PART_ATTEMPTS = 3;
const PART_RETRY_BACKOFF_MS = [2000, 5000];

type MultipartStartResponse = {
  ok: boolean;
  protocol: 'r2_multipart_v1';
  upload_id: string;
  client_upload_id: string;
  batch_id: string;
  storage_key: string;
  source_filename: string;
  source_size_bytes: number;
  part_size_bytes: number;
  expected_part_count: number;
  completed_part_count: number;
  upload_status: string;
  local_cleanup_required: boolean;
  resumed_existing_start: boolean;
};

type MultipartStatusResponse = {
  ok: boolean;
  upload_id: string;
  batch_id: string;
  storage_key: string;
  source_filename: string;
  source_size_bytes: number;
  status: string;
  part_size_bytes: number;
  expected_part_count: number;
  completed_part_count: number;
  completed_parts: Array<{
    part_number: number;
    etag: string;
    size_bytes: number;
  }>;
  local_cleanup_required: boolean;
  local_cleanup_status: string;
};

type MultipartPartUrlResponse = {
  ok: boolean;
  upload_id: string;
  part_number: number;
  size_bytes: number;
  upload_url: string;
};

type MultipartCompleteResponse = {
  ok: boolean;
  upload_id: string;
  upload_status: string;
  storage_key: string;
  source_size_bytes: number;
  verified_size_bytes: number;
  verified_at: string;
  local_cleanup_required: boolean;
  local_cleanup_status: string;
};

export type LargeUploadProgress = {
  stage: 'inspecting' | 'starting' | 'uploading' | 'completing' | 'cleaning' | 'verified';
  uploadedParts: number;
  totalParts: number;
  progress: number;
  uploadId?: string;
  batchId?: string;
};

export type LargeUploadResult = {
  uploadId: string;
  batchId: string;
  storageKey: string;
  sourceSizeBytes: number;
  verifiedAt: string | null;
};

type LargeUploadInput = {
  sourceUri: string;
  filename: string;
  mimeType: string;
  batchId?: string | null;
  onProgress?: (progress: LargeUploadProgress) => void;
};

function emit(
  input: LargeUploadInput,
  ledger: DurableMultipartUpload | null,
  stage: LargeUploadProgress['stage'],
  uploadedParts: number,
  totalParts: number
): void {
  input.onProgress?.({
    stage,
    uploadedParts,
    totalParts,
    progress: totalParts > 0 ? uploadedParts / totalParts : 0,
    uploadId: ledger?.uploadId,
    batchId: ledger?.batchId,
  });
}

function expectedPartSize(ledger: DurableMultipartUpload, partNumber: number): number {
  if (partNumber < ledger.expectedPartCount) return ledger.partSizeBytes;
  return ledger.sourceSizeBytes - (ledger.partSizeBytes * (ledger.expectedPartCount - 1));
}

function durablePartsFromStatus(status: MultipartStatusResponse): DurableMultipartPart[] {
  return status.completed_parts.map((part) => ({
    partNumber: Number(part.part_number),
    etag: String(part.etag),
    sizeBytes: Number(part.size_bytes),
  }));
}

async function persistFailure(
  ledger: DurableMultipartUpload,
  error: unknown
): Promise<DurableMultipartUpload> {
  return upsertDurableMultipartUpload({
    ...ledger,
    status: 'failed',
    lastError: error instanceof Error ? error.message : 'Large upload failed',
  });
}

async function confirmLocalCleanup(
  input: LargeUploadInput,
  ledger: DurableMultipartUpload,
  verifiedAt: string | null
): Promise<LargeUploadResult> {
  emit(input, ledger, 'cleaning', ledger.expectedPartCount, ledger.expectedPartCount);
  const pending = await upsertDurableMultipartUpload({
    ...ledger,
    status: 'cleanup_pending',
    lastError: null,
  });

  try {
    const evidence = await cleanupVerifiedUploadArtifacts({
      sourceUri: pending.sourceUri,
      expectedSourceSize: pending.sourceSizeBytes,
      temporaryUris: pending.temporaryUris,
    });

    await operatorFetch('/api/operator/upload/multipart/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        upload_id: pending.uploadId,
        cleanup_status: 'confirmed',
        artifact_count: evidence.artifactCount,
        reclaimed_bytes: evidence.reclaimedBytes,
        source_preserved: evidence.sourcePreserved,
      }),
    });

    await removeDurableMultipartUpload(pending.localId);
    emit(input, pending, 'verified', pending.expectedPartCount, pending.expectedPartCount);
    return {
      uploadId: pending.uploadId,
      batchId: pending.batchId,
      storageKey: pending.storageKey,
      sourceSizeBytes: pending.sourceSizeBytes,
      verifiedAt,
    };
  } catch (error) {
    const reader = getSportReelSourceReader();
    let sourcePreserved = false;
    try {
      const source = await reader.inspectSource(pending.sourceUri);
      sourcePreserved = source.sizeBytes === pending.sourceSizeBytes;
    } catch {
      sourcePreserved = false;
    }

    if (sourcePreserved) {
      try {
        await operatorFetch('/api/operator/upload/multipart/cleanup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            upload_id: pending.uploadId,
            cleanup_status: 'failed',
            artifact_count: 0,
            reclaimed_bytes: 0,
            source_preserved: true,
            error: error instanceof Error ? error.message : 'Local cleanup failed',
          }),
        });
      } catch {
        // Keep the local ledger so cleanup evidence can be reconciled on the next app start.
      }
    }

    await persistFailure(pending, error);
    throw error;
  }
}

async function reconcileWithServer(
  input: LargeUploadInput,
  ledger: DurableMultipartUpload
): Promise<{ ledger: DurableMultipartUpload; status: MultipartStatusResponse }> {
  const status = await operatorFetch<MultipartStatusResponse>(
    '/api/operator/upload/multipart/status',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload_id: ledger.uploadId }),
    }
  );

  if (
    status.storage_key !== ledger.storageKey
    || status.source_size_bytes !== ledger.sourceSizeBytes
    || status.part_size_bytes !== ledger.partSizeBytes
    || status.expected_part_count !== ledger.expectedPartCount
  ) {
    throw new Error('Durable multipart state does not match the selected source. Upload was stopped safely.');
  }

  const reconciled = await upsertDurableMultipartUpload({
    ...ledger,
    batchId: status.batch_id,
    completedParts: durablePartsFromStatus(status),
    status: status.status === 'completing' ? 'completing' : ledger.status,
    lastError: null,
  });
  emit(input, reconciled, 'uploading', reconciled.completedParts.length, reconciled.expectedPartCount);
  return { ledger: reconciled, status };
}

async function uploadOnePart(
  ledger: DurableMultipartUpload,
  partNumber: number
): Promise<DurableMultipartPart> {
  const reader = getSportReelSourceReader();
  const offset = (partNumber - 1) * ledger.partSizeBytes;
  const expectedSize = expectedPartSize(ledger, partNumber);

  let recorded: DurableMultipartPart | null = null;
  await withRetry(
    async () => {
      const partTarget = await operatorFetch<MultipartPartUrlResponse>(
        '/api/operator/upload/multipart/part-url',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ upload_id: ledger.uploadId, part_number: partNumber }),
        }
      );
      if (partTarget.size_bytes !== expectedSize) {
        throw new Error(`Part ${partNumber} size changed: expected ${expectedSize}, server returned ${partTarget.size_bytes}.`);
      }

      const bytes = await reader.readRange(ledger.sourceUri, offset, expectedSize);
      if (bytes.byteLength !== expectedSize) {
        throw new Error(`Part ${partNumber} read returned ${bytes.byteLength} bytes; expected ${expectedSize}.`);
      }

      const response = await fetch(partTarget.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: bytes as unknown as BodyInit,
      });
      if (!response.ok) {
        throw new Error(`R2 part ${partNumber} upload failed with status ${response.status}.`);
      }

      const etag = response.headers.get('etag')?.trim();
      if (!etag) {
        throw new Error(`R2 part ${partNumber} response did not expose the exact ETag.`);
      }

      await operatorFetch('/api/operator/upload/multipart/record-part', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: ledger.uploadId,
          part_number: partNumber,
          etag,
          size_bytes: expectedSize,
        }),
      });

      recorded = { partNumber, etag, sizeBytes: expectedSize };
    },
    {
      maxAttempts: MAX_PART_ATTEMPTS,
      backoffMs: PART_RETRY_BACKOFF_MS,
    }
  );

  if (!recorded) throw new Error(`Part ${partNumber} did not produce a durable ETag.`);
  return recorded;
}

async function resumeUpload(
  input: LargeUploadInput,
  initialLedger: DurableMultipartUpload
): Promise<LargeUploadResult> {
  const reader = getSportReelSourceReader();
  const source = await reader.inspectSource(initialLedger.sourceUri);
  if (!source.seekable) {
    throw new Error('source_not_seekable: selected SD / USB provider cannot resume by byte offset.');
  }
  if (source.sizeBytes !== initialLedger.sourceSizeBytes) {
    throw new Error(`Selected source changed size from ${initialLedger.sourceSizeBytes} to ${source.sizeBytes}.`);
  }
  if (initialLedger.partSizeBytes > source.maxRangeBytes) {
    throw new Error(`Native source reader limit ${source.maxRangeBytes} is smaller than part size ${initialLedger.partSizeBytes}.`);
  }

  let { ledger, status } = await reconcileWithServer(input, initialLedger);
  if (status.status === 'verified') {
    return confirmLocalCleanup(input, ledger, null);
  }
  if (['aborted', 'superseded', 'size_mismatch'].includes(status.status)) {
    throw new Error(`Multipart upload cannot resume from server status ${status.status}.`);
  }

  try {
    const completed = new Map(ledger.completedParts.map((part) => [part.partNumber, part]));
    for (let partNumber = 1; partNumber <= ledger.expectedPartCount; partNumber += 1) {
      if (completed.has(partNumber)) continue;
      const part = await uploadOnePart(ledger, partNumber);
      completed.set(partNumber, part);
      ledger = await upsertDurableMultipartUpload({
        ...ledger,
        status: 'uploading',
        completedParts: [...completed.values()].sort((left, right) => left.partNumber - right.partNumber),
        lastError: null,
      });
      emit(input, ledger, 'uploading', completed.size, ledger.expectedPartCount);
    }

    ledger = await upsertDurableMultipartUpload({
      ...ledger,
      status: 'completing',
      lastError: null,
    });
    emit(input, ledger, 'completing', ledger.expectedPartCount, ledger.expectedPartCount);

    const completedUpload = await operatorFetch<MultipartCompleteResponse>(
      '/api/operator/upload/multipart/complete',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: ledger.uploadId }),
      }
    );
    if (
      completedUpload.upload_status !== 'verified'
      || completedUpload.verified_size_bytes !== ledger.sourceSizeBytes
    ) {
      throw new Error('R2 multipart completion did not return an exact size-matched verified source.');
    }

    return confirmLocalCleanup(input, ledger, completedUpload.verified_at);
  } catch (error) {
    await persistFailure(ledger, error);
    throw error;
  }
}

export async function uploadLargeExternalSource(
  input: LargeUploadInput
): Promise<LargeUploadResult> {
  emit(input, null, 'inspecting', 0, 0);
  const reader = getSportReelSourceReader();
  const source = await reader.inspectSource(input.sourceUri);
  if (!source.seekable) {
    throw new Error('source_not_seekable: choose an SD / USB provider that supports random access.');
  }
  if (!Number.isSafeInteger(source.sizeBytes) || source.sizeBytes <= 0) {
    throw new Error('The selected source does not expose a stable positive size.');
  }

  const existing = await findDurableMultipartUpload({
    sourceUri: input.sourceUri,
    sourceSizeBytes: source.sizeBytes,
  });
  if (existing) return resumeUpload(input, existing);

  const pendingStart = await getOrCreatePendingMultipartStart({
    sourceUri: input.sourceUri,
    sourceFilename: input.filename,
    mimeType: input.mimeType,
    sourceSizeBytes: source.sizeBytes,
  });

  emit(input, null, 'starting', 0, 0);
  const started = await operatorFetch<MultipartStartResponse>(
    '/api/operator/upload/multipart/start',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_upload_id: pendingStart.requestId,
        filename: input.filename,
        mimeType: input.mimeType,
        size: source.sizeBytes,
        batch_id: input.batchId ?? undefined,
        local_cleanup_required: true,
      }),
    }
  );
  if (started.client_upload_id !== pendingStart.requestId) {
    throw new Error('Multipart start returned a different idempotency identifier.');
  }

  const now = new Date().toISOString();
  const ledger = await upsertDurableMultipartUpload({
    version: 1,
    localId: `${started.upload_id}:${input.sourceUri}`,
    sourceUri: input.sourceUri,
    sourceFilename: input.filename,
    mimeType: input.mimeType,
    sourceSizeBytes: source.sizeBytes,
    uploadId: started.upload_id,
    batchId: started.batch_id,
    storageKey: started.storage_key,
    partSizeBytes: started.part_size_bytes,
    expectedPartCount: started.expected_part_count,
    completedParts: [],
    temporaryUris: [],
    status: 'uploading',
    createdAt: now,
    updatedAt: now,
    lastError: null,
  });
  await removePendingMultipartStart(pendingStart.requestId);

  return resumeUpload(input, ledger);
}

export async function sweepAbandonedUploadCache(): Promise<{
  artifactCount: number;
  reclaimedBytes: number;
  failures: string[];
}> {
  return sweepStaleSportReelUploadArtifacts({
    activeTemporaryUris: await activeMultipartTemporaryUris(),
  });
}
