import AsyncStorage from '@react-native-async-storage/async-storage';
import { decode } from 'base64-arraybuffer';
import * as FileSystem from 'expo-file-system';
import { operatorFetch } from './operatorApi';
import { isRetryableUploadError, UploadHttpError, withRetry } from './uploadQueue';

const RECORD_PREFIX = 'sportreel.multipart-upload.v1:';
const ACTIVE_BATCH_KEY = 'sportreel.multipart-upload.active-batch.v1';
const PART_UPLOAD_ATTEMPTS = 3;
const PART_RETRY_BACKOFF_MS = [1500, 4000];

export type MultipartUploadPart = {
  partNumber: number;
  etag: string;
  size: number;
};

export type PersistedMultipartUpload = {
  version: 1;
  clientUploadId: string;
  batchId: string;
  sourceUri: string;
  filename: string;
  mimeType: string;
  sourceSizeBytes: number;
  storageKey: string;
  uploadId: string;
  partSizeBytes: number;
  parts: MultipartUploadPart[];
  status: 'uploading' | 'failed' | 'verified';
  uploadedBytes: number;
  externalSource: boolean;
  error: string | null;
  updatedAt: string;
};

export type MultipartUploadSession = {
  batch_id?: string | null;
  storage_key?: string | null;
  multipart_upload_id?: string | null;
  part_size_bytes?: number | null;
  multipart_reused?: boolean;
  already_complete?: boolean;
  existing_size_bytes?: number | null;
};

type MultipartServerStatus = {
  ok: boolean;
  state: 'in_progress' | 'completed' | 'missing';
  parts: MultipartUploadPart[];
  uploadedBytes: number;
  objectSize: number | null;
};

type PartUrlResponse = {
  ok: true;
  already_complete: boolean;
  upload_url?: string;
  size?: number | null;
};

type CompleteResponse = {
  ok: true;
  verified: true;
  storage_key: string;
  size: number;
  etag: string | null;
  parts_count: number;
};

export type ResumeMultipartUploadInput = {
  clientUploadId: string;
  batchId: string;
  sourceUri: string;
  filename: string;
  mimeType: string;
  sourceSizeBytes: number;
  externalSource: boolean;
  session: MultipartUploadSession;
  onProgress?: (uploadedBytes: number, totalBytes: number) => void;
};

const recordKey = (clientUploadId: string) => `${RECORD_PREFIX}${clientUploadId}`;
const nowIso = () => new Date().toISOString();

function parseApiStatus(error: unknown): unknown {
  if (!(error instanceof Error)) return error;
  const match = error.message.match(/^API\s+(\d+):/);
  return match ? new UploadHttpError(Number(match[1]), error.message) : error;
}

async function multipartAction<T>(body: Record<string, unknown>): Promise<T> {
  try {
    return await operatorFetch<T>('/api/operator/upload/multipart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw parseApiStatus(error);
  }
}

async function saveRecord(record: PersistedMultipartUpload): Promise<void> {
  await Promise.all([
    AsyncStorage.setItem(recordKey(record.clientUploadId), JSON.stringify(record)),
    AsyncStorage.setItem(ACTIVE_BATCH_KEY, record.batchId),
  ]);
}

async function loadRecord(clientUploadId: string): Promise<PersistedMultipartUpload | null> {
  const raw = await AsyncStorage.getItem(recordKey(clientUploadId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PersistedMultipartUpload;
    return parsed?.version === 1 ? parsed : null;
  } catch {
    return null;
  }
}

function normalizedParts(parts: MultipartUploadPart[]): MultipartUploadPart[] {
  return [...parts]
    .filter((part) => Number.isInteger(part.partNumber) && part.partNumber > 0 && part.etag && part.size >= 0)
    .sort((left, right) => left.partNumber - right.partNumber);
}

function uploadedBytes(parts: MultipartUploadPart[]): number {
  return normalizedParts(parts).reduce((sum, part) => sum + part.size, 0);
}

function expectedPartSize(totalBytes: number, partSizeBytes: number, partNumber: number): number {
  const offset = (partNumber - 1) * partSizeBytes;
  return Math.max(0, Math.min(partSizeBytes, totalBytes - offset));
}

function isStagedExternalSource(record: PersistedMultipartUpload): boolean {
  return Boolean(
    record.externalSource
      && FileSystem.cacheDirectory
      && record.sourceUri.startsWith(FileSystem.cacheDirectory),
  );
}

async function cleanupStagedSource(record: PersistedMultipartUpload): Promise<void> {
  if (!isStagedExternalSource(record)) return;
  try {
    await FileSystem.deleteAsync(record.sourceUri, { idempotent: true });
  } catch {
    // A verified or explicitly discarded upload must not fail because cache
    // cleanup was unavailable. The cache directory remains app-scoped.
  }
}

/**
 * Read exactly one bounded multipart range. expo-file-system 18 performs a
 * single native read for each range, and a valid stream may return fewer bytes
 * than requested. Repeat from the next file offset until the requested range
 * is full; never materialize the whole video in JavaScript memory.
 */
async function readPart(sourceUri: string, offset: number, length: number): Promise<ArrayBuffer> {
  const chunks: Uint8Array[] = [];
  let cursor = offset;
  let remaining = length;
  let total = 0;

  while (remaining > 0) {
    const encoded = await FileSystem.readAsStringAsync(sourceUri, {
      encoding: FileSystem.EncodingType.Base64,
      position: cursor,
      length: remaining,
    });
    const buffer = decode(encoded);
    const bytes = new Uint8Array(buffer);
    if (bytes.byteLength === 0) break;
    chunks.push(bytes);
    cursor += bytes.byteLength;
    remaining -= bytes.byteLength;
    total += bytes.byteLength;
  }

  if (total !== length) {
    throw new Error(`Source part read mismatch at byte ${offset}: expected ${length}, read ${total}`);
  }
  const combined = new Uint8Array(length);
  let targetOffset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, targetOffset);
    targetOffset += chunk.byteLength;
  }
  return combined.buffer;
}

async function serverStatus(storageKey: string, uploadId: string): Promise<MultipartServerStatus> {
  return multipartAction<MultipartServerStatus>({
    action: 'status',
    storage_key: storageKey,
    upload_id: uploadId,
  });
}

async function authoritativeUploadedPart(
  storageKey: string,
  uploadId: string,
  partNumber: number,
  expectedSize: number,
): Promise<MultipartUploadPart> {
  const status = await serverStatus(storageKey, uploadId);
  const part = status.parts.find((candidate) => candidate.partNumber === partNumber);
  if (!part || part.size !== expectedSize || !part.etag) {
    throw new Error(`R2 did not confirm uploaded part ${partNumber} with ${expectedSize} bytes`);
  }
  return part;
}

async function uploadPart(
  storageKey: string,
  uploadId: string,
  partNumber: number,
  bytes: ArrayBuffer,
): Promise<MultipartUploadPart> {
  return withRetry(async () => {
    const signed = await multipartAction<PartUrlResponse>({
      action: 'part_url',
      storage_key: storageKey,
      upload_id: uploadId,
      part_number: partNumber,
    });
    if (signed.already_complete) {
      throw new UploadHttpError(409, 'Multipart upload was already completed while uploading a part');
    }
    if (!signed.upload_url) throw new Error(`Missing signed URL for multipart part ${partNumber}`);

    const response = await fetch(signed.upload_url, { method: 'PUT', body: bytes });
    if (!response.ok) {
      if (response.status === 404) {
        throw new UploadHttpError(409, 'Multipart upload no longer exists');
      }
      throw new UploadHttpError(response.status, `Multipart part ${partNumber} failed with status ${response.status}`);
    }

    const responseEtag = response.headers.get('etag')?.trim() ?? '';
    if (responseEtag) return { partNumber, etag: responseEtag, size: bytes.byteLength };

    // Native clients normally receive ETag directly. If a proxy strips it,
    // reconcile against R2 instead of trusting an unverified client value.
    return authoritativeUploadedPart(storageKey, uploadId, partNumber, bytes.byteLength);
  }, {
    maxAttempts: PART_UPLOAD_ATTEMPTS,
    backoffMs: PART_RETRY_BACKOFF_MS,
    shouldRetry: isRetryableUploadError,
  });
}

function freshRecord(
  input: ResumeMultipartUploadInput,
  storageKey: string,
  uploadId: string,
  partSizeBytes: number,
): PersistedMultipartUpload {
  return {
    version: 1,
    clientUploadId: input.clientUploadId,
    batchId: input.batchId,
    sourceUri: input.sourceUri,
    filename: input.filename,
    mimeType: input.mimeType,
    sourceSizeBytes: input.sourceSizeBytes,
    storageKey,
    uploadId,
    partSizeBytes,
    parts: [],
    status: 'uploading',
    uploadedBytes: 0,
    externalSource: input.externalSource,
    error: null,
    updatedAt: nowIso(),
  };
}

async function markVerified(record: PersistedMultipartUpload): Promise<PersistedMultipartUpload> {
  const verified = {
    ...record,
    status: 'verified' as const,
    uploadedBytes: record.sourceSizeBytes,
    error: null,
    updatedAt: nowIso(),
  };
  await saveRecord(verified);
  await cleanupStagedSource(verified);
  return verified;
}

export async function resumeMultipartUpload(input: ResumeMultipartUploadInput): Promise<PersistedMultipartUpload> {
  const storageKey = input.session.storage_key?.trim() ?? '';
  const uploadId = input.session.multipart_upload_id?.trim() ?? '';
  const partSizeBytes = Number(input.session.part_size_bytes);
  if (!storageKey) throw new Error('Multipart session is missing storage_key');
  if (!Number.isSafeInteger(input.sourceSizeBytes) || input.sourceSizeBytes <= 0) throw new Error('Source file size is unavailable');
  if (!Number.isSafeInteger(partSizeBytes) || partSizeBytes < 5 * 1024 * 1024) throw new Error('Multipart session returned an invalid part size');

  const existingSize = input.session.existing_size_bytes;
  if (input.session.already_complete) {
    if (existingSize !== input.sourceSizeBytes) {
      throw new Error(`Existing R2 object size mismatch: expected ${input.sourceSizeBytes}, found ${existingSize ?? 'unknown'}`);
    }
    const completeRecord = await markVerified(freshRecord(input, storageKey, uploadId, partSizeBytes));
    input.onProgress?.(input.sourceSizeBytes, input.sourceSizeBytes);
    return completeRecord;
  }
  if (!uploadId) throw new Error('Multipart session is missing upload_id');

  const persisted = await loadRecord(input.clientUploadId);
  let record = persisted && persisted.storageKey === storageKey && persisted.uploadId === uploadId
    ? { ...persisted, sourceUri: input.sourceUri, sourceSizeBytes: input.sourceSizeBytes, error: null }
    : freshRecord(input, storageKey, uploadId, partSizeBytes);

  try {
    const status = await serverStatus(storageKey, uploadId);
    if (status.state === 'completed') {
      if (status.objectSize !== input.sourceSizeBytes) {
        throw new Error(`Completed R2 object size mismatch: expected ${input.sourceSizeBytes}, found ${status.objectSize ?? 'unknown'}`);
      }
      record = await markVerified({ ...record, parts: [] });
      input.onProgress?.(input.sourceSizeBytes, input.sourceSizeBytes);
      return record;
    }
    if (status.state !== 'in_progress') throw new UploadHttpError(409, 'Multipart upload no longer exists');

    record = {
      ...record,
      partSizeBytes,
      parts: normalizedParts(status.parts),
      uploadedBytes: status.uploadedBytes,
      status: 'uploading',
      error: null,
      updatedAt: nowIso(),
    };
    await saveRecord(record);
    input.onProgress?.(record.uploadedBytes, input.sourceSizeBytes);

    const partCount = Math.ceil(input.sourceSizeBytes / partSizeBytes);
    for (let partNumber = 1; partNumber <= partCount; partNumber += 1) {
      const size = expectedPartSize(input.sourceSizeBytes, partSizeBytes, partNumber);
      const existingPart = record.parts.find((part) => part.partNumber === partNumber);
      if (existingPart?.size === size) continue;

      const offset = (partNumber - 1) * partSizeBytes;
      const bytes = await readPart(input.sourceUri, offset, size);
      const uploaded = await uploadPart(storageKey, uploadId, partNumber, bytes);
      record.parts = normalizedParts([
        ...record.parts.filter((part) => part.partNumber !== partNumber),
        uploaded,
      ]);
      record.uploadedBytes = uploadedBytes(record.parts);
      record.updatedAt = nowIso();
      await saveRecord(record);
      input.onProgress?.(record.uploadedBytes, input.sourceSizeBytes);
    }

    const finalStatus = await serverStatus(storageKey, uploadId);
    if (finalStatus.state !== 'in_progress') {
      if (finalStatus.state === 'completed' && finalStatus.objectSize === input.sourceSizeBytes) {
        record = await markVerified({ ...record, parts: [] });
        input.onProgress?.(input.sourceSizeBytes, input.sourceSizeBytes);
        return record;
      }
      throw new Error('Multipart upload changed state before completion');
    }

    const authoritativeBytes = uploadedBytes(finalStatus.parts);
    if (authoritativeBytes !== input.sourceSizeBytes) {
      throw new Error(`Multipart byte total mismatch before completion: expected ${input.sourceSizeBytes}, found ${authoritativeBytes}`);
    }

    const completed = await multipartAction<CompleteResponse>({
      action: 'complete',
      storage_key: storageKey,
      upload_id: uploadId,
      expected_size_bytes: input.sourceSizeBytes,
    });
    if (!completed.verified || completed.size !== input.sourceSizeBytes) {
      throw new Error(`Multipart completion verification mismatch for ${storageKey}`);
    }

    record = await markVerified({ ...record, parts: normalizedParts(finalStatus.parts) });
    input.onProgress?.(input.sourceSizeBytes, input.sourceSizeBytes);
    return record;
  } catch (error) {
    record = {
      ...record,
      status: 'failed',
      error: error instanceof Error ? error.message : 'Multipart upload failed',
      updatedAt: nowIso(),
    };
    await saveRecord(record);
    throw error;
  }
}

export async function loadActiveMultipartBatch(): Promise<{ batchId: string; uploads: PersistedMultipartUpload[] } | null> {
  const batchId = await AsyncStorage.getItem(ACTIVE_BATCH_KEY);
  if (!batchId) return null;
  const keys = (await AsyncStorage.getAllKeys()).filter((key) => key.startsWith(RECORD_PREFIX));
  if (!keys.length) return null;
  const entries = await AsyncStorage.multiGet(keys);
  const uploads = entries.flatMap(([, raw]) => {
    if (!raw) return [];
    try {
      const record = JSON.parse(raw) as PersistedMultipartUpload;
      return record?.version === 1 && record.batchId === batchId ? [record] : [];
    } catch {
      return [];
    }
  });
  if (!uploads.length) return null;
  uploads.sort((left, right) => left.filename.localeCompare(right.filename));
  return { batchId, uploads };
}

export async function clearPersistedMultipartBatch(batchId: string): Promise<void> {
  const keys = (await AsyncStorage.getAllKeys()).filter((key) => key.startsWith(RECORD_PREFIX));
  const entries = await AsyncStorage.multiGet(keys);
  const matching: Array<{ key: string; record: PersistedMultipartUpload | null }> = [];
  for (const [key, raw] of entries) {
    if (!raw) continue;
    try {
      const record = JSON.parse(raw) as PersistedMultipartUpload;
      if (record.batchId === batchId) matching.push({ key, record });
    } catch {
      matching.push({ key, record: null });
    }
  }
  await Promise.all(matching.map(({ record }) => record ? cleanupStagedSource(record) : Promise.resolve()));
  await AsyncStorage.multiRemove(matching.map(({ key }) => key));
  if ((await AsyncStorage.getItem(ACTIVE_BATCH_KEY)) === batchId) {
    await AsyncStorage.removeItem(ACTIVE_BATCH_KEY);
  }
}

export async function abortPersistedMultipartUpload(record: PersistedMultipartUpload): Promise<void> {
  if (record.uploadId) {
    await multipartAction({
      action: 'abort',
      storage_key: record.storageKey,
      upload_id: record.uploadId,
    });
  }
  await cleanupStagedSource(record);
  await AsyncStorage.removeItem(recordKey(record.clientUploadId));
}
