import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { githubDispatchError } from '@/lib/github-dispatch-error';

// Simple batchless reset. GitHub serializes reset and processing in one workflow.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-reset', 3, 3600);
  if (limited) return limited;
  let body: { full_clean?: boolean } = {};
  try { body = await req.json(); } catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }); }
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: 'GitHub dispatch is not configured' }, { status: 503 });
  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main', inputs: { reset: 'true', full_clean: String(body.full_clean === true), batch_id: '', pipeline_run_id: '' } }),
    });
    if (response.status !== 204) return NextResponse.json({ error: githubDispatchError(response.status, await response.text()) }, { status: 502 });
    return NextResponse.json({ ok: true, full_clean: body.full_clean === true, github_actions_url: `https://github.com/${repo}/actions/workflows/pipeline-run.yml` });
  } catch (error) {
    return NextResponse.json({ error: `GitHub dispatch failed: ${error instanceof Error ? error.message : 'unknown error'}` }, { status: 502 });
  }
}
