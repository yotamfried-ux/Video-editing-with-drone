import type {
  BackgroundUploadJob,
  SportReelSourceReaderNativeModule,
} from '../../../../modules/sportreel-source-reader/src/SportReelSourceReaderModule';
import { assignSharedUploadBatchId } from './uploadQueue';

export type BackgroundUploadSelection = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  batch_id?: string | null;
};

export type BackgroundNativeApi = Pick<
  SportReelSourceReaderNativeModule,
  | 'enqueueBackgroundUpload'
  | 'persistTreePermission'
  | 'listBackgroundUploads'
  | 'resumeEligibleBackgroundUploads'
  | 'retryBackgroundUpload'
  | 'forgetVerifiedBackgroundUploads'
>;

export type BackgroundUploadClientDeps = {
  native: BackgroundNativeApi;
  getOperatorSecret: () => Promise<string | null>;
  apiBaseUrl: string;
  /** Reserve `count` intended files on the server batch so partial batches can never look "ready". */
  reserveBatchSlots: (batchId: string, count: number) => Promise<void>;
  loadReservations: () => Promise<Record<string, string[]>>;
  saveReservations: (next: Record<string, string[]>) => Promise<void>;
};

export type BackgroundItemPatch = {
  status: 'queued' | 'uploading' | 'verified' | 'failed';
  progress: number;
  error: string | null;
  batch_id: string;
};

export type BackgroundBatchSummary = { total: number; verified: number; failed: number; active: number };

export function mapBackgroundJobToItemPatch(job: BackgroundUploadJob): BackgroundItemPatch {
  const base = { progress: Math.round(job.progress * 100), batch_id: job.batchId };
  switch (job.status) {
    case 'verified':
      return { ...base, status: 'verified', progress: 100, error: null };
    case 'failed':
      return { ...base, status: 'failed', error: job.lastError ?? 'Upload failed' };
    case 'retry_wait':
      return { ...base, status: 'uploading', error: `Waiting to retry: ${job.lastError ?? 'connection interrupted'}` };
    case 'queued':
      return { ...base, status: 'queued', error: null };
    default:
      return { ...base, status: 'uploading', error: null };
  }
}

export function summarizeBackgroundBatch(jobs: BackgroundUploadJob[], batchId: string): BackgroundBatchSummary {
  const batch = jobs.filter((job) => job.batchId === batchId);
  const verified = batch.filter((job) => job.status === 'verified').length;
  const failed = batch.filter((job) => job.status === 'failed').length;
  return { total: batch.length, verified, failed, active: batch.length - verified - failed };
}

/** The client-side half of the gate: the server's verified-batch gate stays authoritative. */
export function pipelineStartBlockedByUploads(items: Array<{ status: string }>): boolean {
  return items.length === 0 || items.some((item) => item.status !== 'verified');
}

/** True while any listed upload is not server-verified. An empty list defers to the server's own batch gate. */
export function hasIncompleteUploads(items: Array<{ status: string }>): boolean {
  return items.some((item) => item.status !== 'verified');
}

export function createBackgroundUploadClient(deps: BackgroundUploadClientDeps) {
  async function requireSecret(): Promise<string> {
    const secret = await deps.getOperatorSecret();
    if (!secret) throw new Error('Operator secret not set. Add it in Operator settings.');
    return secret;
  }

  return {
    async enqueueBatch(
      selection: BackgroundUploadSelection[],
      currentBatchId: string | null
    ): Promise<{ batchId: string; jobs: BackgroundUploadJob[] }> {
      if (!selection.length) throw new Error('Select at least one video to upload.');
      const secret = await requireSecret();
      const batchId = assignSharedUploadBatchId(selection, currentBatchId);

      const ledger = await deps.loadReservations();
      const reserved = new Set(ledger[batchId] ?? []);
      const fresh = selection.filter((item) => !reserved.has(item.uri));
      if (fresh.length) {
        await deps.reserveBatchSlots(batchId, fresh.length);
        await deps.saveReservations({ ...ledger, [batchId]: [...reserved, ...fresh.map((item) => item.uri)] });
      }

      const jobs: BackgroundUploadJob[] = [];
      for (const item of selection) {
        jobs.push(await deps.native.enqueueBackgroundUpload({
          batchId,
          sourceUri: item.uri,
          filename: item.filename,
          mimeType: item.mimeType,
          apiBaseUrl: deps.apiBaseUrl,
          operatorSecret: secret,
        }));
      }
      return { batchId, jobs };
    },

    /** Runs on screen mount / app foreground: re-arm unfinished work, then read durable truth. */
    async reconcile(): Promise<BackgroundUploadJob[]> {
      const secret = await deps.getOperatorSecret();
      await deps.native.resumeEligibleBackgroundUploads(secret);
      return deps.native.listBackgroundUploads();
    },

    async persistTreePermission(treeUri: string): Promise<boolean> {
      return deps.native.persistTreePermission(treeUri);
    },

    async retry(localId: string): Promise<BackgroundUploadJob | null> {
      return deps.native.retryBackgroundUpload(localId, await requireSecret());
    },

    async forgetBatch(batchId: string): Promise<number> {
      const count = await deps.native.forgetVerifiedBackgroundUploads(batchId);
      const ledger = await deps.loadReservations();
      if (ledger[batchId]) {
        const { [batchId]: _removed, ...rest } = ledger;
        await deps.saveReservations(rest);
      }
      return count;
    },
  };
}
