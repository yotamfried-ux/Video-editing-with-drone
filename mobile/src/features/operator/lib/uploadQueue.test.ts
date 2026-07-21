import {
  isRetryableUploadError,
  runQueue,
  UploadHttpError,
  withRetry,
} from './uploadQueue';

describe('withRetry', () => {
  it('returns the result on first success without waiting', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest.fn().mockResolvedValue('ok');

    const result = await withRetry(task, { maxAttempts: 3, backoffMs: [10, 20], wait });

    expect(result).toBe('ok');
    expect(task).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it('retries after a transient failure using full jitter under the configured cap', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest
      .fn()
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce('ok');

    const result = await withRetry(task, {
      maxAttempts: 3,
      backoffMs: [2000, 5000],
      wait,
      random: () => 0.25,
    });

    expect(result).toBe('ok');
    expect(task).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledWith(500);
  });

  it('gives up and throws the last error once maxAttempts is exhausted', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const error1 = new Error('attempt 1 failed');
    const error2 = new Error('attempt 2 failed');
    const error3 = new Error('attempt 3 failed');
    const task = jest
      .fn()
      .mockRejectedValueOnce(error1)
      .mockRejectedValueOnce(error2)
      .mockRejectedValueOnce(error3);

    await expect(withRetry(task, {
      maxAttempts: 3,
      backoffMs: [2000, 5000],
      wait,
      random: () => 1,
    })).rejects.toBe(error3);

    expect(task).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenNthCalledWith(1, 2000);
    expect(wait).toHaveBeenNthCalledWith(2, 5000);
  });

  it('calls onAttempt before every attempt so the app can fetch a fresh URL', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const onAttempt = jest.fn();
    const task = jest
      .fn()
      .mockRejectedValueOnce(new Error('fail once'))
      .mockResolvedValueOnce('ok');

    await withRetry(task, { maxAttempts: 3, backoffMs: [10], wait, onAttempt });

    expect(onAttempt.mock.calls.map((call) => call[0])).toEqual([1, 2]);
  });

  it('does not retry non-transient client errors', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest.fn().mockRejectedValue(new UploadHttpError(400));

    await expect(withRetry(task, {
      maxAttempts: 3,
      backoffMs: [100, 200],
      wait,
      shouldRetry: isRetryableUploadError,
    })).rejects.toMatchObject({ status: 400 });

    expect(task).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it.each([403, 408, 425, 429, 500, 503])('retries transient HTTP status %s', async (status) => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest
      .fn()
      .mockRejectedValueOnce(new UploadHttpError(status))
      .mockResolvedValueOnce('ok');

    await expect(withRetry(task, {
      maxAttempts: 2,
      backoffMs: [100],
      wait,
      random: () => 0.5,
      shouldRetry: isRetryableUploadError,
    })).resolves.toBe('ok');

    expect(wait).toHaveBeenCalledWith(50);
  });
});

describe('isRetryableUploadError', () => {
  it('treats network errors as retryable and validation errors as terminal', () => {
    expect(isRetryableUploadError(new Error('network unavailable'))).toBe(true);
    expect(isRetryableUploadError(new UploadHttpError(401))).toBe(false);
    expect(isRetryableUploadError(new UploadHttpError(404))).toBe(false);
  });
});

describe('runQueue', () => {
  it('settles every item independently so one failure does not stop the rest', async () => {
    const items = [1, 2, 3, 4, 5];
    const worker = jest.fn(async (item: number) => {
      if (item === 3) throw new Error(`item ${item} failed`);
    });

    const results = await runQueue(items, worker, 3);

    expect(worker).toHaveBeenCalledTimes(5);
    expect(results.map((result) => result.status)).toEqual([
      'fulfilled',
      'fulfilled',
      'rejected',
      'fulfilled',
      'fulfilled',
    ]);
  });

  it('never exceeds the concurrency limit', async () => {
    const items = Array.from({ length: 6 }, (_, index) => index);
    let inFlight = 0;
    let maxInFlight = 0;

    await runQueue(items, async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
    }, 2);

    expect(maxInFlight).toBeLessThanOrEqual(2);
  });

  it('processes SD/USB uploads one file at a time in order', async () => {
    const order: string[] = [];
    await runQueue(['a', 'b', 'c'], async (item) => {
      await new Promise((resolve) => setTimeout(resolve, 1));
      order.push(item);
    }, 1);

    expect(order).toEqual(['a', 'b', 'c']);
  });

  it('supports retrying only the previously failed subset', async () => {
    const items = ['ok1', 'bad1', 'ok2', 'bad2'];
    let failFirstPass = true;
    const worker = async (item: string) => {
      if (failFirstPass && item.startsWith('bad')) throw new Error(`${item} failed`);
    };

    const firstPass = await runQueue(items, worker, 3);
    const failedItems = items.filter((_, index) => firstPass[index].status === 'rejected');
    expect(failedItems).toEqual(['bad1', 'bad2']);

    failFirstPass = false;
    const retryPass = await runQueue(failedItems, worker, 3);
    expect(retryPass.every((result) => result.status === 'fulfilled')).toBe(true);
  });
});
