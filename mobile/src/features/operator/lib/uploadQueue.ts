export type RetryOptions = {
  maxAttempts: number;
  backoffMs: number[];
  onAttempt?: (attempt: number) => void;
  shouldRetry?: (error: unknown, attempt: number) => boolean;
  wait?: (ms: number) => Promise<void>;
};

export type BatchScopedUpload = {
  batch_id?: string | null;
};

const defaultWait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function errorStatus(error: unknown): number | null {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = Number((error as { status?: unknown }).status);
    if (Number.isInteger(status)) return status;
  }

  if (error instanceof Error) {
    const match = error.message.match(/(?:API\s+|status\s+)(\d{3})\b/i);
    if (match?.[1]) return Number(match[1]);
  }

  return null;
}

export function isRetryableUploadError(error: unknown): boolean {
  const status = errorStatus(error);
  if (status !== null) {
    if (status === 408 || status === 429 || status >= 500) return true;
    if (status >= 400 && status < 500) return false;
  }

  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    if (
      message.includes('network request failed')
      || message.includes('failed to fetch')
      || message.includes('network error')
      || message.includes('timeout')
      || message.includes('timed out')
      || message.includes('aborterror')
      || message.includes('connection')
      || message.includes('socket')
      || message.includes('offline')
    ) {
      return true;
    }
  }

  // Preserve the previous retry behavior for unknown/non-HTTP failures.
  return true;
}

export function createClientBatchId(now = new Date(), random = Math.random()): string {
  const stamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return `batch_${stamp}_${random.toString(36).slice(2, 10)}`;
}

/**
 * Assigns one stable batch ID to a complete user selection before any upload
 * session is initialized. This lets gallery uploads stay concurrent without a
 * race where several no-batch requests each create a different durable batch.
 */
export function assignSharedUploadBatchId<T extends BatchScopedUpload>(
  items: T[],
  currentBatchId?: string | null,
  createBatchId: () => string = createClientBatchId
): string {
  const candidates = [
    ...items.map((item) => item.batch_id?.trim()).filter((value): value is string => Boolean(value)),
    currentBatchId?.trim() || null,
  ].filter((value): value is string => Boolean(value));
  const unique = [...new Set(candidates)];
  if (unique.length > 1) {
    throw new Error(`Selected uploads span multiple durable batches: ${unique.join(', ')}`);
  }

  const batchId = unique[0] ?? createBatchId();
  if (!batchId) throw new Error('Unable to create a durable upload batch ID');
  for (const item of items) item.batch_id = batchId;
  return batchId;
}

function isBatchScopedUpload(value: unknown): value is BatchScopedUpload {
  return typeof value === 'object' && value !== null && 'batch_id' in value;
}

/**
 * Runs `task` up to `maxAttempts` times, waiting `backoffMs[attempt - 1]` (or the
 * last configured backoff, once exhausted) between attempts. `onAttempt` fires
 * before every attempt, including the first, so callers can re-fetch anything
 * time-sensitive (e.g. a signed upload URL) right before each try rather than
 * reusing one fetched at the start.
 */
export async function withRetry<T>(task: () => Promise<T>, options: RetryOptions): Promise<T> {
  const wait = options.wait ?? defaultWait;
  let lastError: unknown;
  for (let attempt = 1; attempt <= options.maxAttempts; attempt += 1) {
    options.onAttempt?.(attempt);
    try {
      return await task();
    } catch (e) {
      lastError = e;
      if (attempt < options.maxAttempts) {
        if (options.shouldRetry && !options.shouldRetry(e, attempt)) break;
        const delay = options.backoffMs[attempt - 1] ?? options.backoffMs[options.backoffMs.length - 1];
        await wait(delay);
      }
    }
  }
  throw lastError;
}

/**
 * Runs `worker` over `items` with at most `concurrencyLimit` in flight at once.
 * Each item's success/failure is isolated (PromiseSettledResult) so one
 * failure doesn't stop the rest of the queue from being processed.
 */
export async function runQueue<T>(
  items: T[],
  worker: (item: T, index: number) => Promise<void>,
  concurrencyLimit: number
): Promise<PromiseSettledResult<void>[]> {
  const batchScopedItems: BatchScopedUpload[] = [];
  for (const item of items) {
    if (isBatchScopedUpload(item)) batchScopedItems.push(item);
  }
  if (items.length > 0 && batchScopedItems.length === items.length) {
    assignSharedUploadBatchId(batchScopedItems);
  }

  const results: PromiseSettledResult<void>[] = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(concurrencyLimit, 1), items.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        const item = items[index];
        if (item === undefined) continue;
        try {
          await worker(item, index);
          results[index] = { status: 'fulfilled', value: undefined };
        } catch (reason) {
          results[index] = { status: 'rejected', reason };
        }
      }
    })
  );
  return results;
}
