import { apiFetch } from './api';

describe('apiFetch', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('exposes the HTTP status on API failures so callers can classify retryability', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      text: async () => JSON.stringify({ error: 'Unauthorized' }),
    } as Response);

    const error = await apiFetch('/api/operator/upload').catch((value) => value);

    expect(error).toMatchObject({
      name: 'ApiRequestError',
      status: 401,
      message: 'API 401: Unauthorized',
    });
  });

  it('aborts a request that stays pending beyond the 30 second client deadline', async () => {
    jest.useFakeTimers();

    global.fetch = jest.fn((_url: string | URL | Request, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('Aborted');
          error.name = 'AbortError';
          reject(error);
        });
      })
    )) as typeof fetch;

    const result = Promise.race([
      apiFetch('/api/operator/upload').then(
        () => 'resolved',
        (error) => error instanceof Error ? error.message : String(error),
      ),
      new Promise<string>((resolve) => setTimeout(() => resolve('still-pending'), 31_000)),
    ]);

    await jest.advanceTimersByTimeAsync(31_000);

    await expect(result).resolves.toBe('API request timed out after 30000ms');
  });
});
