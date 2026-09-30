/** Server runtime for the shared cleanup service: real R2/Supabase deps + durable run tracking. */
import { supabaseAdmin } from './supabase-admin';
import {
  abortR2MultipartUpload, deleteR2Object, listR2AllObjects, listR2MultipartUploads,
} from './r2-storage';
import {
  CLEANUP_CONFIRMATION, emptyTotals, runCleanupStep, summarize, takeInventory,
  type ActiveStateCounts, type CleanupDatabase, type CleanupStorage, type InventorySummary,
  type SbFile, type StepTotals, type Verification,
} from './video-storage-cleanup';
import type { StorageCleanRun } from '../types/operator-contracts';

export { CLEANUP_CONFIRMATION };

const STALE_RUN_MS = 10 * 60 * 1000;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isRunId = (value: unknown): value is string => typeof value === 'string' && UUID_RE.test(value);

export class CleanupError extends Error {
  constructor(readonly status: number, readonly code: string, message: string, readonly runId?: string) {
    super(message);
  }
}

async function listSupabaseFilesRecursive(bucket: string, path = ''): Promise<SbFile[]> {
  const out: SbFile[] = [];
  for (let offset = 0; ; offset += 100) {
    const { data, error } = await supabaseAdmin.storage.from(bucket).list(path, { limit: 100, offset });
    if (error) {
      if (/not found/i.test(error.message)) return out; // bucket absent: nothing to clean
      throw new Error(`Supabase list ${bucket} failed: ${error.message}`);
    }
    if (!data?.length) break;
    for (const entry of data) {
      const full = path ? `${path}/${entry.name}` : entry.name;
      if (entry.id === null || entry.id === undefined) out.push(...(await listSupabaseFilesRecursive(bucket, full)));
      else out.push({ path: full, size: (entry.metadata as { size?: number } | null)?.size ?? null });
    }
    if (data.length < 100) break;
  }
  return out;
}

export const realStorage: CleanupStorage = {
  listR2All: listR2AllObjects,
  listR2Multipart: listR2MultipartUploads,
  deleteR2Object,
  abortR2Multipart: abortR2MultipartUpload,
  listSupabaseFiles: (bucket) => listSupabaseFilesRecursive(bucket),
  async removeSupabaseFiles(bucket, paths) {
    const { error } = await supabaseAdmin.storage.from(bucket).remove(paths);
    if (error) throw new Error(`Supabase remove ${bucket} failed: ${error.message}`);
  },
};

export const realDatabase: CleanupDatabase = {
  async activeCounts() {
    const { data, error } = await supabaseAdmin.rpc('active_video_state_counts');
    if (error) throw new Error(`active_video_state_counts failed: ${error.message}`);
    return data as ActiveStateCounts;
  },
  async neutralize(runId) {
    const { data, error } = await supabaseAdmin.rpc('neutralize_active_video_state', { p_run_id: runId });
    if (error) throw new CleanupError(409, 'neutralize_failed', error.message);
    return data as Record<string, number>;
  },
};

type RunRow = {
  id: string; status: StorageCleanRun['status']; phase: string;
  before_summary: (InventorySummary & { active_state?: ActiveStateCounts }) | null;
  totals: StepTotals & { initial_total?: number; neutralized?: Record<string, number> };
  verification: Verification | null; error: string | null;
};

const sanitizeError = (e: unknown) => (e instanceof Error ? e.message : String(e)).slice(0, 300);

function toRun(row: RunRow): StorageCleanRun {
  const initial = row.totals.initial_total ?? 0;
  const deleted = (row.totals.r2_deleted ?? 0) + (row.totals.multipart_aborted ?? 0) + (row.totals.reels_removed ?? 0);
  const v = row.verification;
  const message = row.status === 'succeeded'
    ? 'Video storage is clean — 0 active videos. You can upload a new set.'
    : row.status === 'running' ? `Cleaning… ${deleted} of ${initial} removed`
    : row.status === 'abandoned' ? 'Cleanup was interrupted. Retry to finish.'
    : `Cleanup failed: ${row.error ?? v?.failures.join('; ') ?? 'verification failed'}. Storage is NOT confirmed clean.`;
  return {
    run_id: row.id,
    status: row.status,
    phase: row.phase,
    progress: { initial_total: initial, deleted, remaining: Math.max(0, initial - deleted) },
    totals: { r2_deleted: row.totals.r2_deleted ?? 0, multipart_aborted: row.totals.multipart_aborted ?? 0, reels_removed: row.totals.reels_removed ?? 0 },
    before: row.before_summary ? stripActive(row.before_summary) : null,
    after: v?.remaining ?? null,
    active_state_before: row.before_summary?.active_state ?? null,
    active_state_after: v?.active_state ?? null,
    neutralized: row.totals.neutralized ?? null,
    failures: v?.failures ?? [],
    error: row.error,
    message,
  };
}

function stripActive(s: InventorySummary & { active_state?: ActiveStateCounts }): InventorySummary {
  const { active_state: _ignored, ...rest } = s;
  void _ignored;
  return rest;
}

const COLUMNS = 'id,status,phase,before_summary,totals,verification,error';

export async function getRun(runId: string): Promise<StorageCleanRun | null> {
  const { data, error } = await supabaseAdmin.from('video_storage_cleanup_runs').select(COLUMNS).eq('id', runId).maybeSingle();
  if (error) throw new Error(error.message);
  return data ? toRun(data as RunRow) : null;
}

export async function getLatestRun(): Promise<StorageCleanRun | null> {
  const { data, error } = await supabaseAdmin.from('video_storage_cleanup_runs').select(COLUMNS)
    .order('started_at', { ascending: false }).limit(1).maybeSingle();
  if (error) throw new Error(error.message);
  return data ? toRun(data as RunRow) : null;
}

export async function previewCleanup(storage: CleanupStorage = realStorage, db: CleanupDatabase = realDatabase) {
  const [inventory, active] = await Promise.all([takeInventory(storage), db.activeCounts()]);
  return { inventory: summarize(inventory), active_state: active };
}

async function createRun(storage: CleanupStorage, db: CleanupDatabase): Promise<RunRow> {
  const active = await db.activeCounts();
  if (active.live_pipeline_runs > 0 || active.live_running_batches > 0) {
    throw new CleanupError(409, 'pipeline_active', 'A pipeline run is active. Wait for it to finish before cleaning.');
  }
  const before = summarize(await takeInventory(storage));
  const insert = () => supabaseAdmin.from('video_storage_cleanup_runs').insert({
    status: 'running', phase: 'deleting',
    before_summary: { ...before, active_state: active },
    totals: { ...emptyTotals(), initial_total: before.total_removable },
  }).select(COLUMNS).single();
  let { data, error } = await insert();
  if (error && error.code === '23505') {
    const { data: running } = await supabaseAdmin.from('video_storage_cleanup_runs')
      .select('id,updated_at').eq('status', 'running').maybeSingle();
    if (running && Date.now() - new Date(running.updated_at as string).getTime() > STALE_RUN_MS) {
      await supabaseAdmin.from('video_storage_cleanup_runs')
        .update({ status: 'abandoned', finished_at: new Date().toISOString(), error: 'stale run superseded' })
        .eq('id', running.id).eq('status', 'running');
      ({ data, error } = await insert());
    } else if (running) {
      throw new CleanupError(409, 'cleanup_in_progress', 'A cleanup is already running.', running.id as string);
    }
  }
  if (error || !data) throw new Error(error?.message ?? 'Could not create cleanup run');
  return data as RunRow;
}

/** Start (no runId) or continue one bounded step of a cleanup run. */
export async function advanceCleanup(opts: {
  runId?: string; budgetMs?: number; storage?: CleanupStorage; db?: CleanupDatabase;
}): Promise<StorageCleanRun> {
  const storage = opts.storage ?? realStorage;
  const db = opts.db ?? realDatabase;
  let row: RunRow;
  if (opts.runId) {
    const { data, error } = await supabaseAdmin.from('video_storage_cleanup_runs').select(COLUMNS).eq('id', opts.runId).maybeSingle();
    if (error) throw new Error(error.message);
    if (!data) throw new CleanupError(404, 'run_not_found', 'Cleanup run not found');
    row = data as RunRow;
    if (row.status !== 'running') return toRun(row);
  } else {
    row = await createRun(storage, db);
  }

  const update = async (patch: Record<string, unknown>) => {
    const { error } = await supabaseAdmin.from('video_storage_cleanup_runs')
      .update({ ...patch, updated_at: new Date().toISOString() }).eq('id', row.id);
    if (error) throw new Error(error.message);
  };

  try {
    const before = stripActive(row.before_summary as InventorySummary);
    const step = await runCleanupStep({ storage, db, runId: row.id, before, budgetMs: opts.budgetMs });
    const totals = {
      ...row.totals,
      r2_deleted: (row.totals.r2_deleted ?? 0) + step.totals.r2_deleted,
      multipart_aborted: (row.totals.multipart_aborted ?? 0) + step.totals.multipart_aborted,
      reels_removed: (row.totals.reels_removed ?? 0) + step.totals.reels_removed,
      ...(step.neutralized ? { neutralized: step.neutralized } : {}),
    };
    if (!step.done) {
      await update({ totals, phase: 'deleting' });
      return toRun({ ...row, totals, phase: 'deleting' });
    }
    const status = step.phase === 'succeeded' ? 'succeeded' : 'failed';
    const patch = { totals, phase: step.phase, status, verification: step.verification, finished_at: new Date().toISOString(),
      error: status === 'failed' ? `verification failed: ${step.verification?.failures.join('; ')}` : null };
    await update(patch);
    return toRun({ ...row, ...patch, verification: step.verification ?? null, status } as RunRow);
  } catch (e) {
    const patch = { status: 'failed', phase: 'failed', error: sanitizeError(e), finished_at: new Date().toISOString() };
    await update(patch).catch(() => undefined);
    return toRun({ ...row, ...patch } as RunRow);
  }
}
