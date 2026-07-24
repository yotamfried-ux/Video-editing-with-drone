import {
  assignSharedUploadBatchId,
  createClientBatchId,
  runQueue,
  withRetry,
} from './uploadQueue';

describe('upload batch identity', () => {
  it('creates a safe stable client batch ID', () => {
    expect(createClientBatchId(new Date('2026-07-24T12:34:56.000Z'), 0.25)).toMatch(
      /^batch_2026-07-24T12-34-56_[a-z0-9]+$/
    );
  });

  it('assigns one generated batch to every item before upload starts', () => {
    const items = [{ batch_id: null }, { batch_id: undefined }, { batch_id: null }];

    const batchId = assignSharedUploadBatchId(items, null, () => 'batch_shared_test');

    expect(batchId).toBe('batch_shared_test');
    expect(items.map((item) => item.batch_id)).toEqual([
      'batch_shared_test',
      'batch_shared_test',
      'batch_shared_test',
    ]);
  });

  it('preserves an existing durable batch and rejects conflicting batches', () => {
    const items = [{ batch_id: 'batch_existing' }, { batch_id: null }];
    expect(assignSharedUploadBatchId(items)).toBe('batch_existing');
    expect(items[1].batch_id).toBe('batch_existing');

    expect(() => assignSharedUploadBatchId([
      { batch_id: 'batch_a' },
      { batch_id: 'batch_b' },
    ])).toThrow('Selected uploads span multiple durable batches');
  });
});

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
    expect(wait).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenNthCalledWith(1, 2000);
    expect(wait).toHaveBeenNthCalledWith(2, 5000);
  });

  it('calls onAttempt before every attempt, including the first', async () => {
    const wait = jest.fn().mockResolvedValue(undefined);
    const onAttempt = jest.fn();
    const task = jest
      .fn()
      .mockRejectedValueOnce(new Error('fail once'))
      .mockResolvedValueOnce('ok');

    await withRetry(task, { maxAttempts: 3, backoffMs: [10], wait, onAttempt });

    expect(onAttempt.mock.calls.map((call) => call[0])).toEqual([1, 2]);
  });

  it('reuses the last backoff value once the backoff list is exhausted', async () => {
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
  it('assigns one batch before concurrent workers inspect their items', async () => {
    const items = [
      { id: 1, batch_id: null as string | null },
      { id: 2, batch_id: null as string | null },
      { id: 3, batch_id: null as string | null },
    ];
    const seenBatchIds: Array<string | null> = [];

    const results = await runQueue(items, async (item) => {
      seenBatchIds.push(item.batch_id);
    }, 3);

    expect(results.every((result) => result.status === 'fulfilled')).toBe(true);
    expect(new Set(seenBatchIds).size).toBe(1);
    expect(seenBatchIds[0]).toMatch(/^batch_/);
    expect(items.every((item) => item.batch_id === seenBatchIds[0])).toBe(true);
  });

  it('fails closed before workers run when selected items conflict on batch identity', async () => {
    const worker = jest.fn();

    await expect(runQueue([
      { batch_id: 'batch_a' },
      { batch_id: 'batch_b' },
    ], worker, 2)).rejects.toThrow('Selected uploads span multiple durable batches');

    expect(worker).not.toHaveBeenCalled();
  });

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

  it('processes SD/USB-style single-file-at-a-time batches strictly in order', async () => {
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

  it('supports retrying only the previously-failed subset', async () => {
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
