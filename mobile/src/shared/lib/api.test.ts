import { ApiError, apiFetch } from './api';

describe('apiFetch', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('preserves the HTTP status on API failures', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'forbidden' }), {
        status: 403,
        statusText: 'Forbidden',
        headers: { 'Content-Type': 'application/json' },
      })
    ) as typeof fetch;

    await expect(apiFetch('/api/operator/test', { timeoutMs: 100 })).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: 'ApiError',
        status: 403,
        message: 'API 403: forbidden',
      })
    );
  });

  it('aborts a request that exceeds its bounded timeout', async () => {
    global.fetch = jest.fn((_, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      })
    )) as typeof fetch;

    await expect(apiFetch('/api/operator/slow', { timeoutMs: 5 }))
      .rejects.toThrow('API timeout after 5ms: /api/operator/slow');
  });

  it('propagates a caller abort instead of mislabeling it as a timeout', async () => {
    const upstream = new AbortController();
    global.fetch = jest.fn((_, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('caller aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      })
    )) as typeof fetch;

    const request = apiFetch('/api/operator/cancelled', {
      timeoutMs: 1000,
      signal: upstream.signal,
    });
    upstream.abort();

    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
  });
});
