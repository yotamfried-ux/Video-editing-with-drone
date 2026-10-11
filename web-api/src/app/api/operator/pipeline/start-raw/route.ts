import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { githubDispatchError } from '@/lib/github-dispatch-error';

// Legacy-style Run Pipeline: read the RAW folder; no upload batch selection.
// The GitHub workflow owns execution and the existing singleton progress feed.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GitHub dispatch is not configured' }, { status: 503 });
  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main', inputs: { reset: 'false', full_clean: 'false', batch_id: '', pipeline_run_id: '' } }),
    });
    if (response.status !== 204) {
      return NextResponse.json({ error: githubDispatchError(response.status, await response.text()) }, { status: 502 });
    }
    return NextResponse.json({ ok: true, github_actions_url: `https://github.com/${repo}/actions/workflows/pipeline-run.yml` });
  } catch (error) {
    return NextResponse.json({ error: `GitHub dispatch failed: ${error instanceof Error ? error.message : 'unknown error'}` }, { status: 502 });
  }
}
