import { API_BASE_URL as BASE } from './publicEnv';

const API_REQUEST_TIMEOUT_MS = 30_000;

export class ApiRequestError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'ApiRequestError';
  }
}

export function shouldRetryApiRequestError(error: unknown): boolean {
  if (!(error instanceof ApiRequestError)) return true;
  if (error.status == null) return true;
  return error.status === 429 || error.status >= 500;
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

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const controller = new AbortController();
  const upstreamSignal = options?.signal;
  let timedOut = false;

  const abortFromUpstream = () => controller.abort();
  if (upstreamSignal?.aborted) {
    controller.abort();
  } else {
    upstreamSignal?.addEventListener('abort', abortFromUpstream, { once: true });
  }

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      signal: controller.signal,
    });
    if (!res.ok) {
      const message = await readFailureMessage(res);
      throw new ApiRequestError(`API ${res.status}: ${message}`, res.status);
    }
    return res.json() as Promise<T>;
  } catch (error) {
    if (timedOut) {
      throw new ApiRequestError(`API request timed out after ${API_REQUEST_TIMEOUT_MS}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    upstreamSignal?.removeEventListener('abort', abortFromUpstream);
  }
}
