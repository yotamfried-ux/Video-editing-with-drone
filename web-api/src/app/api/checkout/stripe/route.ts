import { randomUUID } from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getPriceForReel } from '@/lib/pricing';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CHECKOUT_SESSION_PATTERN = /^[A-Za-z0-9_-]{16,120}$/;

type PaymentRow = {
  download_token: string | null;
  stripe_payment_intent_id: string | null;
};

async function paymentForIntent(intentId: string): Promise<PaymentRow | null> {
  const { data, error } = await supabaseAdmin
    .from('payments')
    .select('download_token, stripe_payment_intent_id')
    .eq('stripe_payment_intent_id', intentId)
    .maybeSingle();
  if (error) throw new Error(`Payment lookup failed: ${error.message}`);
  return data;
}

function checkoutResponse(clientSecret: string | null, amountMinor: number, downloadToken: string) {
  if (!clientSecret) throw new Error('Stripe returned no PaymentIntent client secret');
  return NextResponse.json({
    clientSecret,
    amount_ils: amountMinor,
    download_token: downloadToken,
  });
}

export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout', 10, 60);
  if (limited) return limited;

  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const reelId = payload.reel_id;
  const email = typeof payload.email === 'string' ? payload.email.trim().toLowerCase() : '';
  const checkoutSessionId = typeof payload.checkout_session_id === 'string'
    ? payload.checkout_session_id.trim()
    : '';

  if (!isUuid(reelId)) {
    return NextResponse.json({ error: 'reel_id must be a valid UUID' }, { status: 400 });
  }
  if (!email || email.length > 254 || !EMAIL_PATTERN.test(email)) {
    return NextResponse.json({ error: 'A valid payer email is required' }, { status: 400 });
  }
  if (!CHECKOUT_SESSION_PATTERN.test(checkoutSessionId)) {
    return NextResponse.json({ error: 'A valid checkout_session_id is required' }, { status: 400 });
  }

  try {
    const amountMinor = await getPriceForReel(reelId);
    const idempotencyKey = `sportreel_checkout_${checkoutSessionId}`;
    const intent = await stripe.paymentIntents.create(
      {
        amount: amountMinor,
        currency: 'ils',
        automatic_payment_methods: { enabled: true },
        receipt_email: email,
        description: `SportReel purchase for reel ${reelId}`,
        metadata: {
          reel_id: reelId,
          payer_email: email,
          checkout_session_id: checkoutSessionId,
        },
      },
      { idempotencyKey },
    );

    const existing = await paymentForIntent(intent.id);
    if (existing?.download_token) {
      return checkoutResponse(intent.client_secret, amountMinor, existing.download_token);
    }

    const downloadToken = randomUUID();
    const { data: payment, error: insertError } = await supabaseAdmin
      .from('payments')
      .insert({
        reel_id: reelId,
        stripe_payment_intent_id: intent.id,
        amount_ils: amountMinor,
        status: 'pending',
        download_token: downloadToken,
      })
      .select('download_token')
      .single();

    if (insertError) {
      // A replay can race with the first request after Stripe has already
      // returned the same PaymentIntent for the idempotency key.
      const replayed = await paymentForIntent(intent.id);
      if (!replayed?.download_token) {
        throw new Error(`Payment persistence failed: ${insertError.message}`);
      }
      return checkoutResponse(intent.client_secret, amountMinor, replayed.download_token);
    }

    if (!payment?.download_token) {
      throw new Error('Payment persistence returned no download token');
    }

    const { error: analyticsError } = await supabaseAdmin.from('analytics_events').insert({
      event_type: 'checkout_started',
      reel_id: reelId,
    });
    if (analyticsError) {
      console.warn('checkout_started analytics insert failed', analyticsError.message);
    }

    return checkoutResponse(intent.client_secret, amountMinor, payment.download_token);
  } catch (error) {
    console.error('Stripe checkout failed', error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Checkout failed' },
      { status: 502 },
    );
  }
}
