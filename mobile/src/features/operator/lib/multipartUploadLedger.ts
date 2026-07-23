import AsyncStorage from '@react-native-async-storage/async-storage';

const LEDGER_KEY = 'sportreel:multipart-upload-ledger:v1';

export type DurableMultipartPart = {
  partNumber: number;
  etag: string;
  sizeBytes: number;
};

export type DurableMultipartUpload = {
  version: 1;
  localId: string;
  sourceUri: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes: number;
  uploadId: string;
  batchId: string;
  storageKey: string;
  partSizeBytes: number;
  expectedPartCount: number;
  completedParts: DurableMultipartPart[];
  temporaryUris: string[];
  status: 'uploading' | 'completing' | 'cleanup_pending' | 'failed';
  createdAt: string;
  updatedAt: string;
  lastError: string | null;
};

export type PendingMultipartStart = {
  requestId: string;
  sourceUri: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes: number;
  createdAt: string;
  updatedAt: string;
};

type LedgerDocument = {
  version: 1;
  uploads: DurableMultipartUpload[];
  pendingStarts: PendingMultipartStart[];
};

let mutationChain: Promise<void> = Promise.resolve();

function emptyLedger(): LedgerDocument {
  return { version: 1, uploads: [], pendingStarts: [] };
}

function isValidUpload(value: unknown): value is DurableMultipartUpload {
  if (!value || typeof value !== 'object') return false;
  const upload = value as Partial<DurableMultipartUpload>;
  return upload.version === 1
    && typeof upload.localId === 'string'
    && typeof upload.sourceUri === 'string'
    && typeof upload.sourceFilename === 'string'
    && typeof upload.mimeType === 'string'
    && Number.isSafeInteger(upload.sourceSizeBytes)
    && Number(upload.sourceSizeBytes) > 0
    && typeof upload.uploadId === 'string'
    && typeof upload.batchId === 'string'
    && typeof upload.storageKey === 'string'
    && Number.isSafeInteger(upload.partSizeBytes)
    && Number(upload.partSizeBytes) > 0
    && Number.isSafeInteger(upload.expectedPartCount)
    && Number(upload.expectedPartCount) > 0
    && Array.isArray(upload.completedParts)
    && Array.isArray(upload.temporaryUris)
    && ['uploading', 'completing', 'cleanup_pending', 'failed'].includes(upload.status ?? '')
    && typeof upload.createdAt === 'string'
    && typeof upload.updatedAt === 'string';
}

function isValidPendingStart(value: unknown): value is PendingMultipartStart {
  if (!value || typeof value !== 'object') return false;
  const pending = value as Partial<PendingMultipartStart>;
  return typeof pending.requestId === 'string'
    && /^[A-Za-z0-9_-]{16,128}$/.test(pending.requestId)
    && typeof pending.sourceUri === 'string'
    && typeof pending.sourceFilename === 'string'
    && typeof pending.mimeType === 'string'
    && Number.isSafeInteger(pending.sourceSizeBytes)
    && Number(pending.sourceSizeBytes) > 0
    && typeof pending.createdAt === 'string'
    && typeof pending.updatedAt === 'string';
}

async function readLedger(): Promise<LedgerDocument> {
  const raw = await AsyncStorage.getItem(LEDGER_KEY);
  if (!raw) return emptyLedger();
  try {
    const parsed = JSON.parse(raw) as Partial<LedgerDocument>;
    if (parsed.version !== 1 || !Array.isArray(parsed.uploads)) return emptyLedger();
    return {
      version: 1,
      uploads: parsed.uploads.filter(isValidUpload),
      pendingStarts: Array.isArray(parsed.pendingStarts)
        ? parsed.pendingStarts.filter(isValidPendingStart)
        : [],
    };
  } catch {
    return emptyLedger();
  }
}

async function writeLedger(ledger: LedgerDocument): Promise<void> {
  await AsyncStorage.setItem(LEDGER_KEY, JSON.stringify(ledger));
}

function serializeMutation<T>(operation: () => Promise<T>): Promise<T> {
  let resolveResult: (value: T | PromiseLike<T>) => void;
  let rejectResult: (reason?: unknown) => void;
  const result = new Promise<T>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject;
  });
  mutationChain = mutationChain
    .catch(() => undefined)
    .then(async () => {
      try {
        resolveResult(await operation());
      } catch (error) {
        rejectResult(error);
      }
    });
  return result;
}

export async function listDurableMultipartUploads(): Promise<DurableMultipartUpload[]> {
  const ledger = await readLedger();
  return ledger.uploads.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export async function findDurableMultipartUpload(input: {
  sourceUri: string;
  sourceSizeBytes: number;
}): Promise<DurableMultipartUpload | null> {
  const uploads = await listDurableMultipartUploads();
  return uploads.find((upload) => (
    upload.sourceUri === input.sourceUri
    && upload.sourceSizeBytes === input.sourceSizeBytes
  )) ?? null;
}

export function getOrCreatePendingMultipartStart(input: {
  sourceUri: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes: number;
}): Promise<PendingMultipartStart> {
  return serializeMutation(async () => {
    const ledger = await readLedger();
    const existing = ledger.pendingStarts.find((pending) => (
      pending.sourceUri === input.sourceUri
      && pending.sourceSizeBytes === input.sourceSizeBytes
      && pending.sourceFilename === input.sourceFilename
    ));
    if (existing) return existing;

    const now = new Date().toISOString();
    const requestId = `android_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}_${Math.random().toString(36).slice(2, 10)}`;
    const pending: PendingMultipartStart = {
      requestId,
      sourceUri: input.sourceUri,
      sourceFilename: input.sourceFilename,
      mimeType: input.mimeType,
      sourceSizeBytes: input.sourceSizeBytes,
      createdAt: now,
      updatedAt: now,
    };
    ledger.pendingStarts.push(pending);
    await writeLedger(ledger);
    return pending;
  });
}

export function removePendingMultipartStart(requestId: string): Promise<void> {
  return serializeMutation(async () => {
    const ledger = await readLedger();
    ledger.pendingStarts = ledger.pendingStarts.filter((pending) => pending.requestId !== requestId);
    await writeLedger(ledger);
  });
}

export function upsertDurableMultipartUpload(
  upload: DurableMultipartUpload
): Promise<DurableMultipartUpload> {
  return serializeMutation(async () => {
    const ledger = await readLedger();
    const next = { ...upload, updatedAt: new Date().toISOString() };
    const index = ledger.uploads.findIndex((candidate) => candidate.localId === upload.localId);
    if (index >= 0) ledger.uploads[index] = next;
    else ledger.uploads.push(next);
    await writeLedger(ledger);
    return next;
  });
}

export function removeDurableMultipartUpload(localId: string): Promise<void> {
  return serializeMutation(async () => {
    const ledger = await readLedger();
    ledger.uploads = ledger.uploads.filter((upload) => upload.localId !== localId);
    await writeLedger(ledger);
  });
}

export async function activeMultipartTemporaryUris(): Promise<ReadonlySet<string>> {
  const uploads = await listDurableMultipartUploads();
  return new Set(uploads.flatMap((upload) => upload.temporaryUris));
}
