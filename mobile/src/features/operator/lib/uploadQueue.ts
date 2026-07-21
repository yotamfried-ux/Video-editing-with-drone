export type RetryOptions = {
  maxAttempts: number;
  backoffMs: number[];
  onAttempt?: (attempt: number) => void;
  wait?: (ms: number) => Promise<void>;
  random?: () => number;
  shouldRetry?: (error: unknown) => boolean;
};

const defaultWait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** HTTP upload failure with a status code that can be classified for retries. */
export class UploadHttpError extends Error {
  readonly status: number;

  constructor(status: number, message = `Upload failed with status ${status}`) {
    super(message);
    this.name = 'UploadHttpError';
    this.status = status;
  }
}

/**
 * Retry network failures and transient HTTP responses. A 403 is retryable here
 * because the caller obtains a new presigned URL before every attempt; it is a
 * common result of an expired upload URL. Validation and other client errors are
 * returned immediately instead of burning the retry/rate-limit budget.
 */
export function isRetryableUploadError(error: unknown): boolean {
  if (!(error instanceof UploadHttpError)) return true;
  return error.status === 403 || error.status === 408 || error.status === 425 || error.status === 429 || error.status >= 500;
}

function retryDelay(capMs: number, random: () => number): number {
  if (capMs <= 0) return 0;
  const sample = Math.max(0, Math.min(1, random()));
  return Math.floor(sample * capMs);
}

/**
 * Obtain a time-sensitive upload session immediately before transferring one
 * item. Keeping this small unit explicit makes it impossible for a queue to
 * create all presigned URLs up front and then let later URLs expire while they
 * wait for earlier uploads.
 */
export async function uploadWithFreshSession<Item, Session>(
  item: Item,
  requestSession: (item: Item) => Promise<Session>,
  uploadAssetToSession: (item: Item, session: Session) => Promise<void>,
): Promise<void> {
  const session = await requestSession(item);
  await uploadAssetToSession(item, session);
}

/**
 * Runs `task` up to `maxAttempts` times. The caller supplies increasing backoff
 * caps and the helper applies full jitter before each retry, matching the retry
 * pattern recommended for transient network and throttling failures. `onAttempt`
 * fires before every attempt so time-sensitive credentials can be refreshed.
 */
export async function withRetry<T>(task: () => Promise<T>, options: RetryOptions): Promise<T> {
  const wait = options.wait ?? defaultWait;
  const random = options.random ?? Math.random;
  const shouldRetry = options.shouldRetry ?? (() => true);
  let lastError: unknown;

  for (let attempt = 1; attempt <= options.maxAttempts; attempt += 1) {
    options.onAttempt?.(attempt);
    try {
      return await task();
    } catch (error) {
      lastError = error;
      if (attempt >= options.maxAttempts || !shouldRetry(error)) throw error;

      const cap = options.backoffMs[attempt - 1] ?? options.backoffMs[options.backoffMs.length - 1] ?? 0;
      await wait(retryDelay(cap, random));
    }
  }

  throw lastError;
}

/**
 * Runs `worker` over `items` with at most `concurrencyLimit` in flight at once.
 * Each item's success/failure is isolated so one failure does not stop the rest
 * of the upload batch.
 */
export async function runQueue<T>(
  items: T[],
  worker: (item: T, index: number) => Promise<void>,
  concurrencyLimit: number
): Promise<PromiseSettledResult<void>[]> {
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
