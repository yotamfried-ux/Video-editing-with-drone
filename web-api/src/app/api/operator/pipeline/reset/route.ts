import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';

// POST /api/operator/pipeline/reset — resets pipeline state and reruns.
// Fires GitHub workflow_dispatch on pipeline-run.yml with reset=true, which:
//   1. Moves all PROCESSED videos back to RAW
//   2. Deletes REVIEW drafts and clears local state
//   3. Reruns the full pipeline on the existing footage
// Rate-limited to 3 calls per hour (destructive operation).
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'pipeline-reset', 3, 3600);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      { error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' },
      { status: 503 },
    );
  }

  const res = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/pipeline-run.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: { reset: 'true' } }),
    }
  );

  if (res.status !== 204) {
    const text = await res.text();
    return NextResponse.json(
      { error: `GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}` },
      { status: 502 },
    );
  }
  return NextResponse.json({ ok: true });
}
