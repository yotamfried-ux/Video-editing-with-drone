import { API_BASE_URL as BASE } from './publicEnv';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(`API ${status}: ${message}`);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function readFailureMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => '');
  if (!text) return res.statusText || 'Request failed';

  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    const value = parsed.error ?? parsed.message;
    if (typeof value === 'string' && value.trim()) return value;
  } catch {
    // Non-JSON response body — fall back to the text below.
  }

  return text.slice(0, 500);
}

export type ApiFetchOptions = RequestInit & {
  timeoutMs?: number;
};

const configuredApiTimeoutMs = Number(process.env.EXPO_PUBLIC_API_TIMEOUT_MS);
const DEFAULT_API_TIMEOUT_MS =
  Number.isFinite(configuredApiTimeoutMs) && configuredApiTimeoutMs > 0
    ? configuredApiTimeoutMs
    : 30_000;

export async function apiFetch<T>(
  path: string,
  options?: ApiFetchOptions
): Promise<T> {
  const {
    timeoutMs = DEFAULT_API_TIMEOUT_MS,
    signal: upstreamSignal,
    ...requestOptions
  } = options ?? {};

  const controller = new AbortController();
  const abortFromUpstream = () => controller.abort();
  if (upstreamSignal?.aborted) {
    controller.abort();
  } else {
    upstreamSignal?.addEventListener('abort', abortFromUpstream, { once: true });
  }

  const boundedTimeoutMs = Math.max(1, timeoutMs);
  const timeout = setTimeout(() => controller.abort(), boundedTimeoutMs);

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...requestOptions.headers },
      ...requestOptions,
      signal: controller.signal,
    });
    if (!res.ok) {
      const message = await readFailureMessage(res);
      throw new ApiError(res.status, message);
    }
    return res.json() as Promise<T>;
  } catch (error) {
    if (controller.signal.aborted && !upstreamSignal?.aborted) {
      throw new Error(`API timeout after ${boundedTimeoutMs}ms: ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    upstreamSignal?.removeEventListener('abort', abortFromUpstream);
  }
}
