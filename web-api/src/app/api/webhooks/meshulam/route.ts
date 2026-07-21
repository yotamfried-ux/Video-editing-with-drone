import { NextRequest, NextResponse } from 'next/server';
import { verifyMeshulamWebhook } from '@/lib/meshulam';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getPriceForReel, minorUnitsToIls } from '@/lib/pricing';

export async function POST(req: NextRequest) {
  const body = await req.json();

  if (!verifyMeshulamWebhook(body, process.env.MESHULAM_WEBHOOK_SECRET!)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  const { transactionId, custom1: reelId, status, amount } = body;
  if (status !== 'success') return NextResponse.json({ ok: true });

  // Locate the pending payment this webhook refers to.
  const { data: payment } = await supabaseAdmin
    .from('payments')
    .select('id, status')
    .eq('meshulam_transaction_id', transactionId)
    .maybeSingle();

  if (!payment) {
    return NextResponse.json({ error: 'Unknown transaction' }, { status: 404 });
  }

  // Idempotency: a redelivered/replayed webhook must not re-process the sale.
  if (payment.status === 'completed') {
    return NextResponse.json({ ok: true });
  }

  // Payment providers and payments.amount_ils use integer agorot. Analytics uses
  // major ILS, so convert only when writing the reporting event.
  const expectedMinorUnits = await getPriceForReel(reelId);
  const paidMinorUnits = Math.round(parseFloat(amount) * 100);
  if (!Number.isFinite(paidMinorUnits) || paidMinorUnits !== expectedMinorUnits) {
    return NextResponse.json({ error: 'Amount mismatch' }, { status: 400 });
  }

  await supabaseAdmin.from('payments')
    .update({ status: 'completed', paid_at: new Date().toISOString() })
    .eq('meshulam_transaction_id', transactionId);

  await supabaseAdmin.from('reels')
    .update({ status: 'sold' })
    .eq('id', reelId);

  const { data: reel } = await supabaseAdmin.from('reels').select('sport, recording_date').eq('id', reelId).single();

  await supabaseAdmin.from('analytics_events').upsert({
    event_type: 'payment_completed',
    reel_id: reelId,
    payment_id: payment.id,
    sport: reel?.sport,
    recording_date: reel?.recording_date,
    revenue_ils: minorUnitsToIls(expectedMinorUnits),
  }, {
    onConflict: 'payment_id,event_type',
    ignoreDuplicates: true,
  });

  return NextResponse.json({ ok: true });
}
