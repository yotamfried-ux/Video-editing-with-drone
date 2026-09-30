/**
 * Shared "clean video storage" service.
 *
 * Used by the Operator API (POST /api/operator/storage/clean) and by the
 * scripts/clean-video-storage.ts CLI so both run exactly the same logic.
 *
 * Scope is fixed here on the server; callers can never choose a bucket or key.
 *  - R2: video-extension objects under the pipeline prefixes only.
 *  - R2: incomplete multipart uploads (aborted via the S3 API).
 *  - Supabase Storage `reels` bucket: video-extension objects (Storage API,
 *    never SQL on storage.objects).
 *  - DB: active references are neutralized by one atomic RPC; history is kept.
 * Never touched: users/auth/profiles, athlete photos, non-video R2 objects,
 * metadata/, videos under unknown prefixes (reported, not deleted), config.
 *
 * The run is resumable and idempotent: every step recomputes the remaining work
 * from live storage state, deletes what it can inside a time budget, and only
 * reports success after a full re-inventory proves the scope is empty.
 */
import type { R2MultipartUpload, R2Object } from './r2-storage';

export const CLEANUP_CONFIRMATION = 'DELETE_OLD_VIDEOS';

export const R2_VIDEO_PREFIXES = [
  'raw/', 'processed/', 'review/', 'approved/', 'pending_payment/', 'pending_uploads/', 'previews/',
] as const;
export const R2_PROTECTED_PREFIXES = ['metadata/'] as const;
export const SUPABASE_VIDEO_BUCKET = 'reels';
export const SUPABASE_PROTECTED_BUCKETS = ['athlete_photos'] as const;
export const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mts', '.mxf'] as const;

const DELETE_CONCURRENCY = 8;
const SUPABASE_REMOVE_BATCH = 50;

export type SbFile = { path: string; size: number | null };

export interface CleanupStorage {
  listR2All(): Promise<R2Object[]>;
  listR2Multipart(): Promise<R2MultipartUpload[]>;
  deleteR2Object(key: string): Promise<void>;
  abortR2Multipart(key: string, uploadId: string): Promise<void>;
  listSupabaseFiles(bucket: string): Promise<SbFile[]>;
  removeSupabaseFiles(bucket: string, paths: string[]): Promise<void>;
}

export interface CleanupDatabase {
  activeCounts(): Promise<ActiveStateCounts>;
  neutralize(runId: string): Promise<Record<string, number>>;
}

export type ActiveStateCounts = {
  source_uploads_active: number;
  upload_batches_active: number;
  reprocess_requests_active: number;
  reels_active: number;
  live_pipeline_runs: number;
  live_running_batches: number;
  paid_reels: number;
};

export type Inventory = {
  r2_video_keys: string[];
  r2_video_bytes: number;
  r2_video_by_prefix: Record<string, number>;
  r2_non_video_total: number;
  r2_unscoped_video_keys: string[];
  r2_multipart: R2MultipartUpload[];
  reels_video_paths: string[];
  reels_non_video_total: number;
  protected_bucket_counts: Record<string, number>;
};

export type InventorySummary = {
  r2_video_objects: number;
  r2_video_bytes: number;
  r2_video_by_prefix: Record<string, number>;
  r2_non_video_objects: number;
  r2_unscoped_video_objects: number;
  r2_incomplete_multipart: number;
  supabase_reels_videos: number;
  supabase_reels_non_video: number;
  protected_bucket_counts: Record<string, number>;
  total_removable: number;
};

const lower = (s: string) => s.toLowerCase();
export const isVideoName = (name: string) => VIDEO_EXTENSIONS.some((ext) => lower(name).endsWith(ext));
export const isProtectedR2Key = (key: string) => R2_PROTECTED_PREFIXES.some((p) => key.startsWith(p));
/** The single gate that decides whether an R2 key may ever be deleted. */
export const isInScopeR2VideoKey = (key: string) =>
  !isProtectedR2Key(key) && R2_VIDEO_PREFIXES.some((p) => key.startsWith(p)) && isVideoName(key) && !key.includes('..');

export async function takeInventory(storage: CleanupStorage): Promise<Inventory> {
  const [objects, multipart, reels, ...protectedFiles] = await Promise.all([
    storage.listR2All(),
    storage.listR2Multipart(),
    storage.listSupabaseFiles(SUPABASE_VIDEO_BUCKET),
    ...SUPABASE_PROTECTED_BUCKETS.map((b) => storage.listSupabaseFiles(b)),
  ]);
  const inv: Inventory = {
    r2_video_keys: [],
    r2_video_bytes: 0,
    r2_video_by_prefix: Object.fromEntries(R2_VIDEO_PREFIXES.map((p) => [p, 0])),
    r2_non_video_total: 0,
    r2_unscoped_video_keys: [],
    r2_multipart: multipart.filter((u) => !isProtectedR2Key(u.key)),
    reels_video_paths: reels.filter((f) => isVideoName(f.path)).map((f) => f.path),
    reels_non_video_total: reels.filter((f) => !isVideoName(f.path)).length,
    protected_bucket_counts: Object.fromEntries(
      SUPABASE_PROTECTED_BUCKETS.map((b, i) => [b, protectedFiles[i].length]),
    ),
  };
  for (const o of objects) {
    if (isInScopeR2VideoKey(o.key)) {
      inv.r2_video_keys.push(o.key);
      inv.r2_video_bytes += o.size ?? 0;
      const prefix = R2_VIDEO_PREFIXES.find((p) => o.key.startsWith(p))!;
      inv.r2_video_by_prefix[prefix] += 1;
    } else if (isVideoName(o.key) && !isProtectedR2Key(o.key)) {
      inv.r2_unscoped_video_keys.push(o.key);
    } else {
      inv.r2_non_video_total += 1;
    }
  }
  return inv;
}

export function summarize(inv: Inventory): InventorySummary {
  return {
    r2_video_objects: inv.r2_video_keys.length,
    r2_video_bytes: inv.r2_video_bytes,
    r2_video_by_prefix: inv.r2_video_by_prefix,
    r2_non_video_objects: inv.r2_non_video_total,
    r2_unscoped_video_objects: inv.r2_unscoped_video_keys.length,
    r2_incomplete_multipart: inv.r2_multipart.length,
    supabase_reels_videos: inv.reels_video_paths.length,
    supabase_reels_non_video: inv.reels_non_video_total,
    protected_bucket_counts: inv.protected_bucket_counts,
    total_removable: inv.r2_video_keys.length + inv.r2_multipart.length + inv.reels_video_paths.length,
  };
}

async function mapLimit<T>(items: T[], limit: number, fn: (item: T) => Promise<void>, shouldStop: () => boolean) {
  let index = 0;
  let firstError: unknown = null;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (index < items.length && !shouldStop() && firstError === null) {
      const item = items[index++];
      try {
        await fn(item);
      } catch (error) {
        firstError = error;
      }
    }
  });
  await Promise.all(workers);
  if (firstError !== null) throw firstError;
}

export type StepTotals = { r2_deleted: number; multipart_aborted: number; reels_removed: number };
export const emptyTotals = (): StepTotals => ({ r2_deleted: 0, multipart_aborted: 0, reels_removed: 0 });

/** Deletes as much in-scope storage as fits in the budget. Throws on the first storage failure. */
export async function deleteStep(
  storage: CleanupStorage,
  inv: Inventory,
  budgetMs: number,
  now: () => number = Date.now,
): Promise<StepTotals> {
  const deadline = now() + budgetMs;
  const stop = () => now() >= deadline;
  const totals = emptyTotals();

  await mapLimit(inv.r2_video_keys, DELETE_CONCURRENCY, async (key) => {
    if (!isInScopeR2VideoKey(key)) throw new Error('Refusing to delete an out-of-scope R2 key');
    await storage.deleteR2Object(key);
    totals.r2_deleted += 1;
  }, stop);

  await mapLimit(inv.r2_multipart, DELETE_CONCURRENCY, async (u) => {
    await storage.abortR2Multipart(u.key, u.uploadId);
    totals.multipart_aborted += 1;
  }, stop);

  const batches: string[][] = [];
  for (let i = 0; i < inv.reels_video_paths.length; i += SUPABASE_REMOVE_BATCH) {
    batches.push(inv.reels_video_paths.slice(i, i + SUPABASE_REMOVE_BATCH));
  }
  await mapLimit(batches, 1, async (paths) => {
    if (!paths.every(isVideoName)) throw new Error('Refusing to remove a non-video Supabase object');
    await storage.removeSupabaseFiles(SUPABASE_VIDEO_BUCKET, paths);
    totals.reels_removed += paths.length;
  }, stop);

  return totals;
}

export type Verification = {
  ok: boolean;
  failures: string[];
  remaining: InventorySummary;
  active_state: ActiveStateCounts;
};

const ACTIVE_ZERO_KEYS: (keyof ActiveStateCounts)[] = [
  'source_uploads_active', 'upload_batches_active', 'reprocess_requests_active', 'reels_active',
];

/** Independent re-inventory. Success is only ever derived from this. */
export async function verifyClean(
  storage: CleanupStorage,
  db: CleanupDatabase,
  before: InventorySummary,
): Promise<Verification> {
  const [inv, active] = await Promise.all([takeInventory(storage), db.activeCounts()]);
  const remaining = summarize(inv);
  const failures: string[] = [];
  if (remaining.r2_video_objects > 0) failures.push(`${remaining.r2_video_objects} R2 video object(s) remain`);
  if (remaining.r2_incomplete_multipart > 0) failures.push(`${remaining.r2_incomplete_multipart} incomplete multipart upload(s) remain`);
  if (remaining.supabase_reels_videos > 0) failures.push(`${remaining.supabase_reels_videos} Supabase reels video(s) remain`);
  for (const key of ACTIVE_ZERO_KEYS) {
    if (active[key] > 0) failures.push(`${active[key]} active DB reference(s) remain in ${key}`);
  }
  if (active.live_pipeline_runs > 0 || active.live_running_batches > 0) failures.push('a pipeline run is active');
  for (const [bucket, count] of Object.entries(before.protected_bucket_counts)) {
    if ((remaining.protected_bucket_counts[bucket] ?? 0) < count) failures.push(`protected bucket ${bucket} lost objects`);
  }
  if (remaining.r2_non_video_objects < before.r2_non_video_objects) failures.push('non-video R2 objects were lost');
  if (remaining.supabase_reels_non_video < before.supabase_reels_non_video) failures.push('non-video reels objects were lost');
  return { ok: failures.length === 0, failures, remaining, active_state: active };
}

export type StepResult = {
  done: boolean;
  totals: StepTotals;
  phase: 'deleting' | 'neutralizing' | 'verifying' | 'succeeded' | 'failed';
  remaining_before_step: number;
  neutralized?: Record<string, number>;
  verification?: Verification;
};

/**
 * One resumable step. Deletes within the budget; when nothing is left, neutralizes the
 * active DB state atomically and verifies. Returns done=true only when verification passed
 * (phase 'succeeded') or verification failed (phase 'failed', done=true, never success).
 */
export async function runCleanupStep(opts: {
  storage: CleanupStorage;
  db: CleanupDatabase;
  runId: string;
  before: InventorySummary;
  budgetMs?: number;
  now?: () => number;
}): Promise<StepResult> {
  const { storage, db, runId, before } = opts;
  const inv = await takeInventory(storage);
  const remaining = summarize(inv).total_removable;
  if (remaining > 0) {
    const totals = await deleteStep(storage, inv, opts.budgetMs ?? 40_000, opts.now);
    const left = remaining - totals.r2_deleted - totals.multipart_aborted - totals.reels_removed;
    if (left > 0) return { done: false, totals, phase: 'deleting', remaining_before_step: remaining };
    return finish(opts, totals, remaining);
  }
  return finish(opts, emptyTotals(), remaining);

  async function finish(o: typeof opts, totals: StepTotals, rem: number): Promise<StepResult> {
    const neutralized = await db.neutralize(runId);
    const verification = await verifyClean(storage, db, before);
    return {
      done: true,
      totals,
      phase: verification.ok ? 'succeeded' : 'failed',
      remaining_before_step: rem,
      neutralized,
      verification,
    };
  }
}
