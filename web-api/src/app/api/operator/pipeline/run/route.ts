import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';

// POST /api/operator/pipeline/run — operator triggers a pipeline run from the app.
//
// Fires a GitHub repository_dispatch (type: new-raw-video) — the same event the
// Drive watcher uses — so the standard "Run Pipeline" workflow starts within
// seconds. Requires two Vercel env vars:
//   GITHUB_DISPATCH_TOKEN — fine-grained PAT with Contents:write on the repo
//   GITHUB_REPO           — e.g. "yotamfried-ux/Video-editing-with-drone"
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      { error: 'GITHUB_DISPATCH_TOKEN / GITHUB_REPO not configured' },
      { status: 503 },
    );
  }

  const res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ event_type: 'new-raw-video' }),
  });

  if (res.status !== 204) {
    const text = await res.text();
    return NextResponse.json(
      { error: `GitHub dispatch failed (${res.status}): ${text.slice(0, 200)}` },
      { status: 502 },
    );
  }
  return NextResponse.json({ ok: true });
}
