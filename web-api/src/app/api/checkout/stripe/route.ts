import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getPriceForReel } from '@/lib/pricing';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout', 10, 60);
  if (limited) return limited;

  const payload = await req.json();
  const reel_id = payload?.reel_id;
  const email = typeof payload?.email === 'string' ? payload.email.trim().toLowerCase() : '';

  if (!isUuid(reel_id)) {
    return NextResponse.json({ error: 'reel_id must be a valid UUID' }, { status: 400 });
  }
  if (!email || email.length > 254 || !EMAIL_PATTERN.test(email)) {
    return NextResponse.json({ error: 'A valid payer email is required' }, { status: 400 });
  }

  const amountIls = await getPriceForReel(reel_id);

  const intent = await stripe.paymentIntents.create({
    amount: amountIls,
    currency: 'ils',
    receipt_email: email,
    metadata: { reel_id, payer_email: email },
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
