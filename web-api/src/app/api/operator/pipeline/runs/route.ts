import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { supabaseAdmin } from '@/lib/supabase-admin';
import type { PipelineRunRow, PipelineRunsResponse } from '@/types/operator-contracts';

// GET /api/operator/pipeline/runs — recent durable pipeline run records.
// The mobile app should read run history through this operator-authenticated API
// instead of direct anon Supabase access.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const limitParam = new URL(req.url).searchParams.get('limit');
  const parsedLimit = Number.parseInt(limitParam ?? '10', 10);
  const limit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), 50) : 10;

  const { data, error } = await supabaseAdmin
    .from('pipeline_runs')
    .select(
      'id, source, status, stage, progress, github_run_url, input_files, output_drafts, error, meta, queued_at, started_at, finished_at, updated_at'
    )
    .order('queued_at', { ascending: false })
    .limit(limit);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json<PipelineRunsResponse>({ runs: (data ?? []) as PipelineRunRow[] });
}
