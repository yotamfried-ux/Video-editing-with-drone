import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getPriceForReel } from '@/lib/pricing';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout', 10, 60);
  if (limited) return limited;

  const { reel_id } = await req.json();
  if (!isUuid(reel_id)) return NextResponse.json({ error: 'reel_id must be a valid UUID' }, { status: 400 });

  const amountIls = await getPriceForReel(reel_id);

  const intent = await stripe.paymentIntents.create({
    amount: amountIls,
    currency: 'ils',
    metadata: { reel_id },
  });

  const { data: payment } = await supabaseAdmin.from('payments').insert({
    reel_id,
    stripe_payment_intent_id: intent.id,
    amount_ils: amountIls,
    status: 'pending',
  }).select('download_token').single();

  await supabaseAdmin.from('analytics_events').insert({
    event_type: 'checkout_started',
    reel_id,
  });

  return NextResponse.json({
    clientSecret: intent.client_secret,
    amount_ils: amountIls,
    download_token: payment?.download_token,
  });
}
