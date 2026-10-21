import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { dispatchOperatorPipelineRun } from '@/lib/pipeline-dispatch';

// Batchless RAW run: durable run row + single-flight guard live in the shared dispatch service.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const limited = await enforceRateLimit(req, 'pipeline-run', 5, 60);
  if (limited) return limited;
  return dispatchOperatorPipelineRun('process');
}
