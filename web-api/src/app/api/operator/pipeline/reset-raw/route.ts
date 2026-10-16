import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { dispatchOperatorPipelineRun } from '@/lib/pipeline-dispatch';

// Batchless reset and rerun. Uses the same tracked dispatch as start-raw so the run is
// visible in Recent pipeline runs and cannot overlap an active run.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-reset', 3, 3600);
  if (limited) return limited;
  let body: { full_clean?: boolean } = {};
  try { body = await req.json(); } catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }); }
  return dispatchOperatorPipelineRun('reset_and_rerun', body.full_clean === true);
}
