import { operatorFetch } from './operatorApi';
import type {
  StorageCleanPreviewResponse,
  StorageCleanRequest,
  StorageCleanRun,
} from '../types/contracts';

export const CLEAN_CONFIRMATION = 'DELETE_OLD_VIDEOS';
export const CLEAN_SUCCESS_MESSAGE = 'Video storage is clean — 0 active videos. You can upload a new set.';
const CLEAN_PATH = '/api/operator/storage/clean';

export type CleanOutcome =
  | { kind: 'success'; run: StorageCleanRun }
  | { kind: 'failed'; run: StorageCleanRun }
  | { kind: 'interrupted'; runId: string | null; error: string };

/** Success is trusted only when the server verified it: status succeeded, no failures, nothing left. */
export function isVerifiedClean(run: StorageCleanRun): boolean {
  return (
    run.status === 'succeeded'
    && run.failures.length === 0
    && run.after !== null
    && run.after.total_removable === 0
    && run.after.r2_video_objects === 0
    && run.after.supabase_reels_videos === 0
    && run.after.r2_incomplete_multipart === 0
  );
}

export const fetchCleanPreview = () => operatorFetch<StorageCleanPreviewResponse>(CLEAN_PATH);

type Post = (body: StorageCleanRequest) => Promise<StorageCleanRun>;

const defaultPost: Post = (body) => operatorFetch<StorageCleanRun>(CLEAN_PATH, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/**
 * Drives one cleanup: start once with the explicit confirmation, then continue the same run
 * until the server reports a terminal status. Never reports success on network errors.
 */
export async function runCleanVideoStorage(
  onProgress: (run: StorageCleanRun) => void,
  post: Post = defaultPost,
  resumeRunId?: string,
): Promise<CleanOutcome> {
  let runId: string | null = resumeRunId ?? null;
  try {
    let run = await post(runId ? { run_id: runId } : { confirmation: CLEAN_CONFIRMATION });
    runId = run.run_id;
    onProgress(run);
    while (run.status === 'running') {
      run = await post({ run_id: run.run_id });
      onProgress(run);
    }
    if (run.status === 'succeeded') {
      return isVerifiedClean(run) ? { kind: 'success', run } : { kind: 'failed', run: { ...run, status: 'failed' } };
    }
    return { kind: 'failed', run };
  } catch (e) {
    return { kind: 'interrupted', runId, error: e instanceof Error ? e.message : String(e) };
  }
}
