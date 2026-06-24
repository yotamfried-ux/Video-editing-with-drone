import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const limitParam = new URL(req.url).searchParams.get('limit');
  const parsedLimit = Number.parseInt(limitParam ?? '10', 10);
  const limit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), 50) : 10;

  const { data, error } = await supabaseAdmin
    .from('delivery_runs')
    .select('id, approved_file_id, approved_file_name, source_video, status, stage, github_run_url, discover_reel_id, error, meta, approved_at, started_at, finished_at, updated_at')
    .order('approved_at', { ascending: false })
    .limit(limit);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ runs: data ?? [] });
}
