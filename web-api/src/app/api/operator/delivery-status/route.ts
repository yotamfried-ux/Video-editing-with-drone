import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';
import type { DeliveryRunRow, DeliveryStatusResponse } from '@/types/operator-contracts';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const limited = await enforceRateLimit(req, 'delivery-status', 120, 60);
  if (limited) return limited;

  const limitParam = new URL(req.url).searchParams.get('limit');
  const parsedLimit = Number.parseInt(limitParam ?? '10', 10);
  const limit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), 50) : 10;

  const { data, error } = await supabaseAdmin
    .from('delivery_runs')
    .select('id, approved_file_id, approved_file_name, source_video, status, stage, github_run_url, discover_reel_id, error, meta, approved_at, started_at, finished_at, updated_at')
    .order('approved_at', { ascending: false })
    .limit(limit);

  if (error) {
    console.error('delivery-status query failed', error.message);
    return NextResponse.json({ error: 'Could not load delivery status' }, { status: 500 });
  }

  return NextResponse.json<DeliveryStatusResponse>({ runs: (data ?? []) as DeliveryRunRow[] });
}
