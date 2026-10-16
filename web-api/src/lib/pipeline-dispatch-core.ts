// Shared, dependency-free dispatch logic for operator-triggered RAW pipeline runs.
//
// Both "Run pipeline" (start-raw) and "Reset and rerun" (reset-raw) go through
// dispatchPipelineRun so they always create a durable pipeline_runs row, pass its id
// to GitHub Actions, and share the same single-flight protection. The module has no
// imports so behaviour tests can run it directly with injected fakes.

export type DispatchMode = 'process' | 'reset_and_rerun';

// A run still queued/running after this long has outlived the workflow's 330-minute timeout.
export const ACTIVE_RUN_WINDOW_MS = 6 * 60 * 60 * 1000;
// The workflow records github_run_id in its first step, seconds after it starts. A row that
// is still uncorrelated after this long was never started (e.g. its pending run was superseded
// or cancelled by GitHub), so it must not block new runs.
export const UNSTARTED_RUN_GRACE_MS = 30 * 60 * 1000;

export type RunRecord = { id: string; queued_at: string };

export type ActiveRun = {
  id: string;
  queued_at: string;
  status: string;
  stage: string | null;
  github_run_id: number | null;
};

export type StoreResult<T> = { data: T | null; error: string | null };

export interface RunStore {
  insertRun(row: Record<string, unknown>): Promise<StoreResult<RunRecord>>;
  // Rows with status queued/running and queued_at >= cutoffIso, excluding excludeId.
  listActiveRuns(cutoffIso: string, excludeId: string): Promise<StoreResult<ActiveRun[]>>;
  updateRun(id: string, patch: Record<string, unknown>, onlyIfStage?: string): Promise<{ error: string | null }>;
}

export type DispatchDeps = {
  store: RunStore;
  fetchImpl: (url: string, init: { method: string; headers: Record<string, string>; body: string }) =>
    Promise<{ status: number; text(): Promise<string> }>;
  describeGithubError: (status: number, bodyText: string) => string;
  repo: string;
  token: string;
  ref: string;
  now?: () => number;
  logError?: (message: string, detail?: unknown) => void;
};

export type DispatchResult = { status: number; body: Record<string, unknown> };

export function workflowUrl(repo: string): string {
  return `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;
}

export function buildRunMeta(mode: DispatchMode, fullClean: boolean): Record<string, unknown> {
  // Never put credentials or tokens here; this row is shown to the operator.
  return {
    requested_by: 'operator_app',
    mode: mode === 'reset_and_rerun' ? 'reset_and_rerun' : 'simple_raw',
    batch_id: '',
    reset_requested: mode === 'reset_and_rerun',
    full_clean_requested: mode === 'reset_and_rerun' && fullClean,
  };
}

export function buildWorkflowInputs(mode: DispatchMode, fullClean: boolean, runId: string): Record<string, string> {
  const reset = mode === 'reset_and_rerun';
  return {
    reset: String(reset),
    full_clean: String(reset && fullClean),
    batch_id: '',
    pipeline_run_id: runId,
  };
}

function parseTime(value: string): number {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : NaN;
}

// True when `run` should block a new dispatch.
export function isBlockingRun(run: ActiveRun, nowMs: number): boolean {
  if (run.status !== 'queued' && run.status !== 'running') return false;
  const queuedAt = parseTime(run.queued_at);
  if (!Number.isFinite(queuedAt)) return true; // fail closed on unreadable timestamps
  const age = nowMs - queuedAt;
  if (age > ACTIVE_RUN_WINDOW_MS) return false;
  const uncorrelated = run.github_run_id == null && (run.stage === 'dispatching' || run.stage === 'workflow_dispatched');
  if (uncorrelated && age > UNSTARTED_RUN_GRACE_MS) return false;
  return true;
}

// Deterministic total order so exactly one of several racing requests proceeds.
export function isEarlier(a: { queued_at: string; id: string }, b: { queued_at: string; id: string }): boolean {
  const ta = parseTime(a.queued_at);
  const tb = parseTime(b.queued_at);
  if (ta !== tb) return ta < tb;
  return a.id < b.id;
}

export async function dispatchPipelineRun(
  opts: { mode: DispatchMode; fullClean?: boolean },
  deps: DispatchDeps,
): Promise<DispatchResult> {
  const { store } = deps;
  const now = deps.now ?? Date.now;
  const logError = deps.logError ?? (() => {});
  const fullClean = opts.mode === 'reset_and_rerun' && opts.fullClean === true;
  const actionsUrl = workflowUrl(deps.repo);

  const { data: run, error: insertError } = await store.insertRun({
    source: 'manual',
    status: 'queued',
    stage: 'dispatching',
    progress: 0,
    github_event: 'workflow_dispatch',
    github_run_url: actionsUrl,
    input_files: [],
    meta: buildRunMeta(opts.mode, fullClean),
  });
  if (insertError || !run) {
    return { status: 500, body: { error: insertError ?? 'Could not create pipeline run' } };
  }

  const fail = async (message: string, stage = 'dispatch_failed') => {
    const { error } = await store.updateRun(run.id, {
      status: 'dispatch_failed', stage, error: message, finished_at: new Date(now()).toISOString(),
    });
    if (error) logError('Failed to finalize pipeline dispatch', error);
  };

  // Single-flight: GitHub keeps only one pending run per concurrency group and cancels an older
  // pending one before any step runs, which would strand its row as "queued". Insert-then-check
  // lets the earliest active row win deterministically even when requests race, and also keeps a
  // reset from starting while processing is active (and vice versa).
  const cutoff = new Date(now() - ACTIVE_RUN_WINDOW_MS).toISOString();
  const { data: active, error: activeError } = await store.listActiveRuns(cutoff, run.id);
  if (activeError) {
    const message = `Could not verify that no pipeline run is active: ${activeError}`;
    await fail(message);
    return { status: 503, body: { error: message, pipeline_run_id: run.id } };
  }
  const earlier = (active ?? []).find((other) => isBlockingRun(other, now()) && isEarlier(other, run));
  if (earlier) {
    const message = `A pipeline run is already active (${String(earlier.id).slice(0, 8)}). Wait for it to finish before starting another.`;
    await fail(message, 'run_already_active');
    return { status: 409, body: { error: message, pipeline_run_id: run.id, active_pipeline_run_id: earlier.id } };
  }

  try {
    const response = await deps.fetchImpl(
      `https://api.github.com/repos/${deps.repo}/actions/workflows/pipeline-run.yml/dispatches`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${deps.token}`,
          Accept: 'application/vnd.github+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ref: deps.ref, inputs: buildWorkflowInputs(opts.mode, fullClean, run.id) }),
      },
    );
    if (response.status !== 204) {
      const message = deps.describeGithubError(response.status, await response.text());
      await fail(message);
      return { status: 502, body: { error: message, pipeline_run_id: run.id } };
    }
  } catch (error) {
    const message = `GitHub dispatch failed: ${error instanceof Error ? error.message : 'unknown error'}`;
    await fail(message);
    return { status: 502, body: { error: message, pipeline_run_id: run.id } };
  }

  const { error: stageError } = await store.updateRun(run.id, { stage: 'workflow_dispatched' }, 'dispatching');
  if (stageError) logError('Failed to record workflow_dispatched stage', stageError);

  return {
    status: 200,
    body: {
      ok: true,
      pipeline_run_id: run.id,
      mode: opts.mode,
      ...(opts.mode === 'reset_and_rerun' ? { full_clean: fullClean } : {}),
      github_actions_url: actionsUrl,
    },
  };
}
