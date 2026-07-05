import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { approveDraftPost } from '@/lib/operator-draft-approve';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  return approveDraftPost(req);
}
