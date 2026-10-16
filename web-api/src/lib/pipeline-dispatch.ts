import { NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { githubDispatchError } from '@/lib/github-dispatch-error';
import {
  dispatchPipelineRun,
  type ActiveRun,
  type DispatchMode,
  type RunRecord,
  type RunStore,
} from '@/lib/pipeline-dispatch-core';

// Supabase-backed run store for the shared dispatch service.
const supabaseRunStore: RunStore = {
  async insertRun(row) {
    const { data, error } = await supabaseAdmin.from('pipeline_runs').insert(row).select('id, queued_at').single();
    return { data: (data as RunRecord | null) ?? null, error: error?.message ?? null };
  },
  async listActiveRuns(cutoffIso, excludeId) {
    const { data, error } = await supabaseAdmin.from('pipeline_runs')
      .select('id, queued_at, status, stage, github_run_id')
      .in('status', ['queued', 'running']).gte('queued_at', cutoffIso).neq('id', excludeId);
    return { data: (data as ActiveRun[] | null) ?? null, error: error?.message ?? null };
  },
  async updateRun(id, patch, onlyIfStage) {
    let query = supabaseAdmin.from('pipeline_runs').update(patch).eq('id', id);
    if (onlyIfStage) query = query.eq('stage', onlyIfStage);
    const { error } = await query;
    return { error: error?.message ?? null };
  },
};

// Route entry point shared by start-raw and reset-raw.
export async function dispatchOperatorPipelineRun(mode: DispatchMode, fullClean = false): Promise<NextResponse> {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GitHub dispatch is not configured' }, { status: 503 });
  const result = await dispatchPipelineRun({ mode, fullClean }, {
    store: supabaseRunStore,
    fetchImpl: (url, init) => fetch(url, init),
    describeGithubError: githubDispatchError,
    repo,
    token,
    ref: process.env.GITHUB_DISPATCH_REF || 'main',
    logError: (message, detail) => console.error(message, detail),
  });
  return NextResponse.json(result.body, { status: result.status });
}
