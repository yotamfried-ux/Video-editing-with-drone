import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ download_token: string }> },
) {
  const limited = await enforceRateLimit(req, 'payment-status', 60, 60);
  if (limited) return limited;

  const { download_token: downloadToken } = await params;
  if (!isUuid(downloadToken)) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const { data: payment, error } = await supabaseAdmin
    .from('payments')
    .select('status')
    .eq('download_token', downloadToken)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: 'Payment status unavailable' }, { status: 503 });
  }
  if (!payment) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const status = payment.status === 'completed'
    ? 'completed'
    : payment.status === 'failed'
      ? 'failed'
      : 'pending';

  return NextResponse.json({ status, ready: status === 'completed' });
}
