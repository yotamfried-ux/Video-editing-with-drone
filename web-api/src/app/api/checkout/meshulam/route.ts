import { NextRequest, NextResponse } from 'next/server';
import { createMeshulamPayment } from '@/lib/meshulam';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getPriceForReel } from '@/lib/pricing';
import { enforceRateLimit } from '@/lib/ratelimit';

export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout', 10, 60);
  if (limited) return limited;

  const { reel_id } = await req.json();
  if (!reel_id) return NextResponse.json({ error: 'reel_id required' }, { status: 400 });

  const amountIls = await getPriceForReel(reel_id);

  const appDomain = process.env.NEXT_PUBLIC_APP_DOMAIN ?? 'sportreel.app';
  const { paymentUrl, transactionId } = await createMeshulamPayment(
    amountIls,
    reel_id,
    `sportreel://success/${reel_id}`,
    `sportreel://checkout/${reel_id}?error=1`,
  );

  const { data: payment } = await supabaseAdmin.from('payments').insert({
    reel_id,
    meshulam_transaction_id: transactionId,
    amount_ils: amountIls,
    status: 'pending',
  }).select('download_token').single();

  await supabaseAdmin.from('analytics_events').insert({
    event_type: 'checkout_started',
    reel_id,
  });

  return NextResponse.json({
    paymentUrl,
    transaction_id: transactionId,
    download_token: payment?.download_token,
    amount_ils: amountIls,
  });
}
