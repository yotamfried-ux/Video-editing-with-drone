import {
  createBackgroundUploadClient,
  hasIncompleteUploads,
  mapBackgroundJobToItemPatch,
  pipelineStartBlockedByUploads,
  summarizeBackgroundBatch,
  type BackgroundUploadClientDeps,
} from './backgroundUploadClient';
import type { BackgroundUploadJob } from '../../../../modules/sportreel-source-reader/src/SportReelSourceReaderModule';

function job(partial: Partial<BackgroundUploadJob> & { localId: string; sourceUri: string }): BackgroundUploadJob {
  return {
    batchId: 'batch_1',
    filename: `${partial.localId}.mp4`,
    status: 'queued',
    attempt: 0,
    lastError: null,
    uploadId: null,
    storageKey: null,
    sourceSizeBytes: 100,
    completedPartCount: 0,
    expectedPartCount: null,
    progress: 0,
    updatedAt: '2026-10-01T00:00:00Z',
    ...partial,
  };
}

function makeDeps(initial: BackgroundUploadJob[] = []) {
  const jobs = new Map(initial.map((j) => [j.localId, j]));
  const reservations: Array<{ batchId: string; count: number }> = [];
  let ledger: Record<string, string[]> = {};
  const native = {
    enqueueBackgroundUpload: jest.fn(async (req: { batchId: string; sourceUri: string; filename: string }) => {
      const localId = `id_${req.batchId}_${req.sourceUri}`;
      const existing = jobs.get(localId);
      if (existing) return existing;
      const created = job({ localId, sourceUri: req.sourceUri, batchId: req.batchId, filename: req.filename });
      jobs.set(localId, created);
      return created;
    }),
    listBackgroundUploads: jest.fn(async () => [...jobs.values()]),
    getBackgroundUpload: jest.fn(),
    persistTreePermission: jest.fn(async () => true),
    resumeEligibleBackgroundUploads: jest.fn(async () => []),
    retryBackgroundUpload: jest.fn(async (id: string) => jobs.get(id) ?? null),
    forgetVerifiedBackgroundUploads: jest.fn(async () => 0),
  };
  const deps: BackgroundUploadClientDeps = {
    native: native as unknown as BackgroundUploadClientDeps['native'],
    getOperatorSecret: jest.fn(async () => 'secret-value'),
    apiBaseUrl: 'https://api.example.invalid',
    reserveBatchSlots: jest.fn(async (batchId: string, count: number) => { reservations.push({ batchId, count }); }),
    loadReservations: jest.fn(async () => ledger),
    saveReservations: jest.fn(async (next: Record<string, string[]>) => { ledger = next; }),
  };
  return { deps, native, jobs, reservations, getLedger: () => ledger };
}

const items = (n: number) => Array.from({ length: n }, (_, i) => ({
  id: `item_${i}`, uri: `content://video/${i}`, filename: `clip${i}.mp4`, mimeType: 'video/mp4', batch_id: null as string | null,
}));

describe('background upload hand-off', () => {
  it('assigns one stable batch id to the whole selection before any enqueue', async () => {
    const { deps, native } = makeDeps();
    const client = createBackgroundUploadClient(deps);
    const selection = items(3);
    const { batchId } = await client.enqueueBatch(selection, null);
    expect(batchId).toMatch(/^batch_/);
    expect(selection.every((i) => i.batch_id === batchId)).toBe(true);
    expect(native.enqueueBackgroundUpload).toHaveBeenCalledTimes(3);
    for (const call of native.enqueueBackgroundUpload.mock.calls) expect(call[0].batchId).toBe(batchId);
  });

  it('reserves the exact selection size on the server before the first native enqueue', async () => {
    const { deps, native, reservations } = makeDeps();
    const order: string[] = [];
    (deps.reserveBatchSlots as jest.Mock).mockImplementation(async () => { order.push('reserve'); });
    native.enqueueBackgroundUpload.mockImplementation(async (r: { sourceUri: string; batchId: string }) => { order.push('enqueue'); return job({ localId: r.sourceUri, sourceUri: r.sourceUri, batchId: r.batchId }); });
    await createBackgroundUploadClient(deps).enqueueBatch(items(4), 'batch_fixed');
    expect(order[0]).toBe('reserve');
    expect(deps.reserveBatchSlots).toHaveBeenCalledWith('batch_fixed', 4);
    expect(reservations).toEqual([]); // overwritten mock above; assertion on call args is authoritative
  });

  it('does not reserve or enqueue twice when the same selection is submitted again', async () => {
    const { deps, native } = makeDeps();
    const client = createBackgroundUploadClient(deps);
    await client.enqueueBatch(items(2), 'batch_fixed');
    await client.enqueueBatch(items(2), 'batch_fixed');
    expect(deps.reserveBatchSlots).toHaveBeenCalledTimes(1);
    // the native layer is idempotent per logical upload; JS may call it again but must reuse the same batch
    expect(native.enqueueBackgroundUpload.mock.calls.every((c) => c[0].batchId === 'batch_fixed')).toBe(true);
  });

  it('only reserves the genuinely new items when a selection grows', async () => {
    const { deps } = makeDeps();
    const client = createBackgroundUploadClient(deps);
    await client.enqueueBatch(items(2), 'batch_fixed');
    await client.enqueueBatch(items(5), 'batch_fixed');
    expect((deps.reserveBatchSlots as jest.Mock).mock.calls.map((c) => c[1])).toEqual([2, 3]);
  });

  it('passes the operator secret and api base to native and never an R2 credential', async () => {
    const { deps, native } = makeDeps();
    await createBackgroundUploadClient(deps).enqueueBatch(items(1), 'batch_fixed');
    const req = native.enqueueBackgroundUpload.mock.calls[0][0] as unknown as Record<string, unknown>;
    expect(req.operatorSecret).toBe('secret-value');
    expect(req.apiBaseUrl).toBe('https://api.example.invalid');
    expect(Object.keys(req).sort()).toEqual(['apiBaseUrl', 'batchId', 'filename', 'mimeType', 'operatorSecret', 'sourceUri']);
  });

  it('fails closed before touching the server when the operator secret is missing', async () => {
    const { deps, native } = makeDeps();
    (deps.getOperatorSecret as jest.Mock).mockResolvedValue(null);
    await expect(createBackgroundUploadClient(deps).enqueueBatch(items(1), 'b')).rejects.toThrow('Operator secret not set');
    expect(deps.reserveBatchSlots).not.toHaveBeenCalled();
    expect(native.enqueueBackgroundUpload).not.toHaveBeenCalled();
  });

  it('rejects a selection that spans conflicting batches', async () => {
    const { deps } = makeDeps();
    const sel = items(2); sel[0].batch_id = 'a'; sel[1].batch_id = 'b';
    await expect(createBackgroundUploadClient(deps).enqueueBatch(sel, null)).rejects.toThrow('multiple durable batches');
  });
});

describe('relaunch reconciliation', () => {
  it('re-schedules unfinished jobs with the current secret and returns durable progress', async () => {
    const { deps, native } = makeDeps([
      job({ localId: 'a', sourceUri: 'content://a', status: 'uploading', completedPartCount: 2, expectedPartCount: 4, progress: 0.5 }),
      job({ localId: 'b', sourceUri: 'content://b', status: 'verified', progress: 1 }),
    ]);
    const result = await createBackgroundUploadClient(deps).reconcile();
    expect(native.resumeEligibleBackgroundUploads).toHaveBeenCalledWith('secret-value');
    expect(result.map((j) => j.localId)).toEqual(['a', 'b']);
    expect(result[0].progress).toBe(0.5);
  });

  it('still lists durable state when no secret is available (resume is skipped, state is not lost)', async () => {
    const { deps, native } = makeDeps([job({ localId: 'a', sourceUri: 'content://a', status: 'retry_wait' })]);
    (deps.getOperatorSecret as jest.Mock).mockResolvedValue(null);
    const result = await createBackgroundUploadClient(deps).reconcile();
    expect(native.resumeEligibleBackgroundUploads).toHaveBeenCalledWith(null);
    expect(result).toHaveLength(1);
  });
});

describe('UI mapping and pipeline gate', () => {
  it('maps durable states to existing upload item states', () => {
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'queued' })).status).toBe('queued');
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'uploading', progress: 0.42 }))).toMatchObject({ status: 'uploading', progress: 42 });
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'completing', progress: 1 })).status).toBe('uploading');
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'retry_wait', lastError: 'network unavailable' }))).toMatchObject({ status: 'uploading', error: 'Waiting to retry: network unavailable' });
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'verified', progress: 1 }))).toMatchObject({ status: 'verified', progress: 100, error: null });
    expect(mapBackgroundJobToItemPatch(job({ localId: 'a', sourceUri: 'u', status: 'failed', lastError: 'api_403' }))).toMatchObject({ status: 'failed', error: 'api_403' });
  });

  it('summarizes a batch from durable jobs only', () => {
    const jobs = [
      job({ localId: 'a', sourceUri: 'a', status: 'verified' }),
      job({ localId: 'b', sourceUri: 'b', status: 'uploading' }),
      job({ localId: 'c', sourceUri: 'c', status: 'failed' }),
      job({ localId: 'd', sourceUri: 'd', status: 'verified', batchId: 'other' }),
    ];
    expect(summarizeBackgroundBatch(jobs, 'batch_1')).toEqual({ total: 3, verified: 1, failed: 1, active: 1 });
  });

  it('blocks pipeline start while any upload is not verified, and when there is nothing to start', () => {
    expect(pipelineStartBlockedByUploads([])).toBe(true);
    expect(pipelineStartBlockedByUploads([{ status: 'verified' }, { status: 'uploading' }])).toBe(true);
    expect(pipelineStartBlockedByUploads([{ status: 'verified' }, { status: 'failed' }])).toBe(true);
    expect(pipelineStartBlockedByUploads([{ status: 'verified' }, { status: 'queued' }])).toBe(true);
    expect(pipelineStartBlockedByUploads([{ status: 'verified' }, { status: 'verified' }])).toBe(false);
  });
});

describe('UI pipeline gate', () => {
  it('treats any non-verified item as incomplete and an empty list as deferring to the server gate', () => {
    expect(hasIncompleteUploads([])).toBe(false);
    expect(hasIncompleteUploads([{ status: 'verified' }])).toBe(false);
    for (const status of ['queued', 'initializing', 'uploading', 'failed']) {
      expect(hasIncompleteUploads([{ status: 'verified' }, { status }])).toBe(true);
    }
  });
});

describe('retry and cleanup', () => {
  it('persists the SAF tree grant through native so a cold worker can read the sources', async () => {
    const { deps, native } = makeDeps();
    await expect(createBackgroundUploadClient(deps).persistTreePermission('content://tree/x')).resolves.toBe(true);
    expect(native.persistTreePermission).toHaveBeenCalledWith('content://tree/x');
  });

  it('retries a failed job through native with the current secret', async () => {
    const { deps, native } = makeDeps([job({ localId: 'a', sourceUri: 'u', status: 'failed' })]);
    await createBackgroundUploadClient(deps).retry('a');
    expect(native.retryBackgroundUpload).toHaveBeenCalledWith('a', 'secret-value');
  });

  it('forgets only verified durable records of the consumed batch', async () => {
    const { deps, native } = makeDeps();
    await createBackgroundUploadClient(deps).forgetBatch('batch_1');
    expect(native.forgetVerifiedBackgroundUploads).toHaveBeenCalledWith('batch_1');
  });
});
