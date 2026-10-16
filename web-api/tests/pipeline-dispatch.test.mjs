// Behavioural tests for the shared RAW dispatch service (no network, no database).
// Run: node --test web-api/tests/pipeline-dispatch.test.mjs   (Node >= 22.18 strips TS types)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  dispatchPipelineRun, isBlockingRun, buildRunMeta, buildWorkflowInputs,
  ACTIVE_RUN_WINDOW_MS, UNSTARTED_RUN_GRACE_MS,
} from '../src/lib/pipeline-dispatch-core.ts';

const T0 = Date.parse('2026-10-16T12:00:00.000Z');

function makeStore({ failInsert = false, failList = false, failUpdate = false, delayInsert = false } = {}) {
  const rows = [];
  let seq = 0;
  return {
    rows,
    async insertRun(row) {
      if (delayInsert) await new Promise((r) => setImmediate(r));
      if (failInsert) return { data: null, error: 'db down' };
      const id = `00000000-0000-4000-8000-${String(++seq).padStart(12, '0')}`;
      const record = { id, queued_at: new Date(T0 + seq).toISOString(), github_run_id: null, ...row };
      rows.push(record);
      return { data: { id, queued_at: record.queued_at }, error: null };
    },
    async listActiveRuns(cutoffIso, excludeId) {
      if (failList) return { data: null, error: 'list failed' };
      return { data: rows.filter((r) => ['queued', 'running'].includes(r.status) && r.queued_at >= cutoffIso && r.id !== excludeId), error: null };
    },
    async updateRun(id, patch, onlyIfStage) {
      if (failUpdate) return { error: 'update failed' };
      const row = rows.find((r) => r.id === id);
      if (row && (!onlyIfStage || row.stage === onlyIfStage)) Object.assign(row, patch);
      return { error: null };
    },
  };
}

function makeDeps(store, { githubStatus = 204, throwFetch = false } = {}) {
  const calls = [];
  return {
    calls,
    deps: {
      store, repo: 'o/r', token: 'secret-token', ref: 'main', now: () => T0 + 1000,
      describeGithubError: (s, t) => `github ${s} ${t}`,
      fetchImpl: async (url, init) => {
        calls.push({ url, init, body: JSON.parse(init.body) });
        if (throwFetch) throw new Error('network down');
        return { status: githubStatus, text: async () => 'boom' };
      },
    },
  };
}

test('normal RAW dispatch creates a durable row and passes its id to the workflow', async () => {
  const store = makeStore(); const { deps, calls } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'process' }, deps);
  assert.equal(res.status, 200);
  assert.equal(calls.length, 1);
  const row = store.rows[0];
  assert.equal(res.body.pipeline_run_id, row.id);
  assert.deepEqual(calls[0].body.inputs, { reset: 'false', full_clean: 'false', batch_id: '', pipeline_run_id: row.id });
  assert.equal(row.status, 'queued'); assert.equal(row.stage, 'workflow_dispatched'); assert.equal(row.progress, 0);
  assert.equal(row.source, 'manual'); assert.equal(row.github_event, 'workflow_dispatch');
  assert.equal(row.meta.mode, 'simple_raw'); assert.equal(row.meta.reset_requested, false);
});

test('reset dispatch is tracked with reset metadata and run id', async () => {
  const store = makeStore(); const { deps, calls } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'reset_and_rerun', fullClean: false }, deps);
  assert.equal(res.status, 200); assert.equal(res.body.full_clean, false);
  const row = store.rows[0];
  assert.deepEqual(calls[0].body.inputs, { reset: 'true', full_clean: 'false', batch_id: '', pipeline_run_id: row.id });
  assert.equal(row.meta.mode, 'reset_and_rerun'); assert.equal(row.meta.reset_requested, true);
  assert.equal(row.meta.full_clean_requested, false);
});

test('full-clean reset forwards full_clean and records it', async () => {
  const store = makeStore(); const { deps, calls } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'reset_and_rerun', fullClean: true }, deps);
  assert.equal(res.body.full_clean, true);
  assert.equal(calls[0].body.inputs.full_clean, 'true');
  assert.equal(store.rows[0].meta.full_clean_requested, true);
});

test('full_clean is ignored for normal processing', () => {
  assert.equal(buildWorkflowInputs('process', true, 'x').full_clean, 'false');
  assert.equal(buildRunMeta('process', true).full_clean_requested, false);
});

test('metadata and dispatch response never contain credentials', async () => {
  const store = makeStore(); const { deps } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'reset_and_rerun', fullClean: true }, deps);
  assert.ok(!JSON.stringify(store.rows).includes('secret-token'));
  assert.ok(!JSON.stringify(res.body).includes('secret-token'));
});

test('GitHub API failure persists a terminal dispatch_failed row', async () => {
  const store = makeStore(); const { deps } = makeDeps(store, { githubStatus: 403 });
  const res = await dispatchPipelineRun({ mode: 'reset_and_rerun' }, deps);
  assert.equal(res.status, 502);
  const row = store.rows[0];
  assert.equal(row.status, 'dispatch_failed'); assert.match(row.error, /github 403/);
  assert.ok(row.finished_at); assert.equal(res.body.pipeline_run_id, row.id);
});

test('network exception during dispatch persists dispatch_failed', async () => {
  const store = makeStore(); const { deps } = makeDeps(store, { throwFetch: true });
  const res = await dispatchPipelineRun({ mode: 'process' }, deps);
  assert.equal(res.status, 502); assert.equal(store.rows[0].status, 'dispatch_failed');
  assert.match(store.rows[0].error, /network down/);
});

test('Supabase insert failure returns 500 and never calls GitHub', async () => {
  const store = makeStore({ failInsert: true }); const { deps, calls } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'process' }, deps);
  assert.equal(res.status, 500); assert.equal(calls.length, 0);
});

test('failure to verify active runs fails closed without dispatching', async () => {
  const store = makeStore({ failList: true }); const { deps, calls } = makeDeps(store);
  const res = await dispatchPipelineRun({ mode: 'process' }, deps);
  assert.equal(res.status, 503); assert.equal(calls.length, 0);
  assert.equal(store.rows[0].status, 'dispatch_failed');
});

test('an active run rejects both processing and reset with 409 and no dispatch', async () => {
  for (const mode of ['process', 'reset_and_rerun']) {
    const store = makeStore(); const first = makeDeps(store);
    await dispatchPipelineRun({ mode: 'process' }, first.deps);
    const second = makeDeps(store);
    const res = await dispatchPipelineRun({ mode, fullClean: true }, second.deps);
    assert.equal(res.status, 409, mode);
    assert.equal(second.calls.length, 0);
    assert.equal(res.body.active_pipeline_run_id, store.rows[0].id);
    assert.equal(store.rows[1].status, 'dispatch_failed'); assert.equal(store.rows[1].stage, 'run_already_active');
  }
});

test('duplicate submission (double tap) dispatches exactly once', async () => {
  const store = makeStore(); const { deps, calls } = makeDeps(store);
  const a = await dispatchPipelineRun({ mode: 'reset_and_rerun' }, deps);
  const b = await dispatchPipelineRun({ mode: 'reset_and_rerun' }, deps);
  assert.deepEqual([a.status, b.status], [200, 409]); assert.equal(calls.length, 1);
});

test('concurrent racing requests dispatch exactly one run, deterministically', async () => {
  const store = makeStore({ delayInsert: true }); const { deps, calls } = makeDeps(store);
  const results = await Promise.all([
    dispatchPipelineRun({ mode: 'process' }, deps),
    dispatchPipelineRun({ mode: 'reset_and_rerun' }, deps),
    dispatchPipelineRun({ mode: 'process' }, deps),
  ]);
  assert.equal(results.filter((r) => r.status === 200).length, 1);
  assert.equal(results.filter((r) => r.status === 409).length, 2);
  assert.equal(calls.length, 1);
  assert.equal(results.find((r) => r.status === 200).body.pipeline_run_id, store.rows[0].id);
});

test('a terminal run (succeeded/failed/cancelled-finalized) does not block the next run', async () => {
  for (const status of ['succeeded', 'failed', 'no_input', 'no_reviewable_drafts', 'dispatch_failed']) {
    const store = makeStore(); const { deps } = makeDeps(store);
    await dispatchPipelineRun({ mode: 'process' }, deps);
    store.rows[0].status = status;
    assert.equal((await dispatchPipelineRun({ mode: 'reset_and_rerun' }, deps)).status, 200, status);
  }
});

test('stranded runs expire so a cancelled pending run cannot block forever', () => {
  const now = T0 + 10 * 60 * 60 * 1000;
  const base = { id: 'a', status: 'queued', stage: 'workflow_dispatched', github_run_id: null };
  // Never started: uncorrelated beyond the grace period.
  assert.equal(isBlockingRun({ ...base, queued_at: new Date(now - UNSTARTED_RUN_GRACE_MS - 1).toISOString() }, now), false);
  // Recently dispatched: still waiting for the workflow to start.
  assert.equal(isBlockingRun({ ...base, queued_at: new Date(now - 60_000).toISOString() }, now), true);
  // Correlated and running: blocks until the workflow timeout window.
  const running = { ...base, status: 'running', stage: 'analyzing', github_run_id: 42 };
  assert.equal(isBlockingRun({ ...running, queued_at: new Date(now - 3 * 3600_000).toISOString() }, now), true);
  assert.equal(isBlockingRun({ ...running, queued_at: new Date(now - ACTIVE_RUN_WINDOW_MS - 1).toISOString() }, now), false);
  // Unreadable timestamps fail closed.
  assert.equal(isBlockingRun({ ...base, queued_at: 'garbage' }, now), true);
});

test('a failed request leaves nothing that blocks the next request', async () => {
  const store = makeStore(); const failing = makeDeps(store, { githubStatus: 500 });
  assert.equal((await dispatchPipelineRun({ mode: 'process' }, failing.deps)).status, 502);
  const ok = makeDeps(store);
  assert.equal((await dispatchPipelineRun({ mode: 'process' }, ok.deps)).status, 200);
});

test('failure to record workflow_dispatched does not fail a successful dispatch', async () => {
  const store = makeStore({ failUpdate: true }); const { deps } = makeDeps(store);
  const logged = []; deps.logError = (m) => logged.push(m);
  assert.equal((await dispatchPipelineRun({ mode: 'process' }, deps)).status, 200);
  assert.ok(logged.length > 0);
});
