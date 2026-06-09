import { NextRequest, NextResponse } from 'next/server';
import { verifyMeshulamWebhook } from '@/lib/meshulam';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function POST(req: NextRequest) {
  const body = await req.json();

  if (!verifyMeshulamWebhook(body, process.env.MESHULAM_WEBHOOK_SECRET!)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  const { transactionId, userId: reelId, status, amount } = body;
  if (status !== 'success') return NextResponse.json({ ok: true });

  await supabaseAdmin.from('payments')
    .update({ status: 'completed', paid_at: new Date().toISOString() })
    .eq('meshulam_transaction_id', transactionId);

  await supabaseAdmin.from('reels')
    .update({ status: 'sold' })
    .eq('id', reelId);

  const { data: reel } = await supabaseAdmin.from('reels').select('sport, recording_date').eq('id', reelId).single();

  await supabaseAdmin.from('analytics_events').insert({
    event_type: 'payment_completed',
    reel_id: reelId,
    sport: reel?.sport,
    recording_date: reel?.recording_date,
    revenue_ils: Math.round(parseFloat(amount) * 100),
  });

  return NextResponse.json({ ok: true });
}
