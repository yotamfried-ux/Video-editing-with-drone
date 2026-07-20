import { runQueue, withRetry } from './uploadQueue';

describe('withRetry', () => {
  it('returns the result on first success without waiting', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest.fn().mockResolvedValue('ok');

    const result = await withRetry(task, { maxAttempts: 3, backoffMs: [10, 20], wait });

    expect(result).toBe('ok');
    expect(task).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it('retries after a failure and succeeds, waiting the configured backoff between attempts', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest
      .fn()
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce('ok');

    const result = await withRetry(task, { maxAttempts: 3, backoffMs: [2000, 5000], wait });

    expect(result).toBe('ok');
    expect(task).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledTimes(1);
    expect(wait).toHaveBeenCalledWith(2000);
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

    await expect(withRetry(task, { maxAttempts: 3, backoffMs: [2000, 5000], wait })).rejects.toBe(error3);

    expect(task).toHaveBeenCalledTimes(3);
    // No wait after the final (exhausted) attempt.
    expect(wait).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenNthCalledWith(1, 2000);
    expect(wait).toHaveBeenNthCalledWith(2, 5000);
  });

  it('calls onAttempt before every attempt, including the first — this is the hook the app uses to fetch a fresh signed URL right before each try', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const onAttempt = jest.fn();
    const task = jest
      .fn()
      .mockRejectedValueOnce(new Error('fail once'))
      .mockResolvedValueOnce('ok');

    await withRetry(task, { maxAttempts: 3, backoffMs: [10], wait, onAttempt });

    expect(onAttempt.mock.calls.map((call) => call[0])).toEqual([1, 2]);
  });

  it('reuses the last backoff value once the backoff list is shorter than maxAttempts - 1', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const task = jest.fn().mockRejectedValue(new Error('always fails'));

    await expect(withRetry(task, { maxAttempts: 4, backoffMs: [100], wait })).rejects.toThrow('always fails');

    expect(wait).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenNthCalledWith(1, 100);
    expect(wait).toHaveBeenNthCalledWith(2, 100);
    expect(wait).toHaveBeenNthCalledWith(3, 100);
  });
});

describe('runQueue', () => {
  it('settles every item independently so one failure does not stop the rest of the batch', async () => {
    const items = [1, 2, 3, 4, 5];
    const worker = jest.fn(async (item: number) => {
      if (item === 3) throw new Error(`item ${item} failed`);
    });

    const results = await runQueue(items, worker, 3);

    expect(worker).toHaveBeenCalledTimes(5);
    expect(results.map((r) => r.status)).toEqual([
      'fulfilled',
      'fulfilled',
      'rejected',
      'fulfilled',
      'fulfilled',
    ]);
    expect((results[2] as PromiseRejectedResult).reason.message).toBe('item 3 failed');
  });

  it('never runs more than concurrencyLimit workers at once', async () => {
    const items = Array.from({ length: 6 }, (_, i) => i);
    let inFlight = 0;
    let maxInFlight = 0;

    const worker = async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
    };

    await runQueue(items, worker, 2);

    expect(maxInFlight).toBeLessThanOrEqual(2);
  });

  it('processes SD/USB-style single-file-at-a-time batches (concurrencyLimit 1) strictly in order', async () => {
    const items = ['a', 'b', 'c'];
    const order: string[] = [];

    await runQueue(
      items,
      async (item) => {
        await new Promise((resolve) => setTimeout(resolve, 1));
        order.push(item);
      },
      1
    );

    expect(order).toEqual(['a', 'b', 'c']);
  });

  it('supports retrying only the previously-failed subset — the "Retry all failed" flow', async () => {
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

    expect(retryPass.every((r) => r.status === 'fulfilled')).toBe(true);
  });
});
