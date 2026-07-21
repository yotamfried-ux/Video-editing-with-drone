import type Stripe from 'stripe';
import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { isUuid } from '@/lib/validate';

type PaymentRow = {
  id: string;
  reel_id: string | null;
  amount_ils: number | string | null;
  status: string | null;
};

async function findPayment(intentId: string): Promise<PaymentRow | null> {
  const { data, error } = await supabaseAdmin
    .from('payments')
    .select('id, reel_id, amount_ils, status')
    .eq('stripe_payment_intent_id', intentId)
    .maybeSingle();
  if (error) throw new Error(`Payment lookup failed: ${error.message}`);
  return data;
}

function validateFulfillment(intent: Stripe.PaymentIntent, payment: PaymentRow): string {
  const reelId = intent.metadata?.reel_id;
  if (!isUuid(reelId)) throw new Error('PaymentIntent is missing a valid reel_id');
  if (payment.reel_id !== reelId) throw new Error('PaymentIntent reel_id does not match the payment row');
  if (intent.currency !== 'ils') throw new Error(`Unexpected PaymentIntent currency: ${intent.currency}`);

  const expectedAmount = Number(payment.amount_ils);
  const receivedAmount = intent.amount_received || intent.amount;
  if (!Number.isSafeInteger(expectedAmount) || expectedAmount <= 0 || receivedAmount !== expectedAmount) {
    throw new Error(`Payment amount mismatch: expected ${expectedAmount}, received ${receivedAmount}`);
  }
  return reelId;
}

async function fulfillPayment(intent: Stripe.PaymentIntent) {
  const payment = await findPayment(intent.id);
  if (!payment) {
    // Ignore PaymentIntents created by other integrations in the same Stripe
    // account, but retry SportReel intents until their durable row exists.
    if (!intent.metadata?.reel_id) return;
    throw new Error(`No payment row exists for PaymentIntent ${intent.id}`);
  }

  const reelId = validateFulfillment(intent, payment);
  const paidAt = new Date().toISOString();
  const { error: paymentError } = await supabaseAdmin
    .from('payments')
    .update({ status: 'completed', paid_at: paidAt })
    .eq('id', payment.id);
  if (paymentError) throw new Error(`Payment completion update failed: ${paymentError.message}`);

  const { error: reelError } = await supabaseAdmin
    .from('reels')
    .update({ status: 'sold' })
    .eq('id', reelId);
  if (reelError) throw new Error(`Reel sold-state update failed: ${reelError.message}`);

  const { data: reel, error: reelReadError } = await supabaseAdmin
    .from('reels')
    .select('sport, recording_date')
    .eq('id', reelId)
    .single();
  if (reelReadError) throw new Error(`Reel lookup failed: ${reelReadError.message}`);

  const { error: analyticsError } = await supabaseAdmin
    .from('analytics_events')
    .upsert({
      event_type: 'payment_completed',
      reel_id: reelId,
      payment_id: payment.id,
      sport: reel?.sport,
      recording_date: reel?.recording_date,
      revenue_ils: (intent.amount_received || intent.amount) / 100,
    }, {
      onConflict: 'payment_id,event_type',
      ignoreDuplicates: true,
    });
  if (analyticsError) throw new Error(`Payment analytics update failed: ${analyticsError.message}`);

  // The PaymentIntent was created with receipt_email. Stripe owns the compliant
  // receipt and sends it after successful capture. SportReel deliberately does
  // not send a second payment-confirmation email from this webhook.
}

async function failPayment(intent: Stripe.PaymentIntent) {
  const payment = await findPayment(intent.id);
  if (!payment || payment.status === 'completed') return;
  const { error } = await supabaseAdmin
    .from('payments')
    .update({ status: 'failed' })
    .eq('id', payment.id)
    .neq('status', 'completed');
  if (error) throw new Error(`Payment failure update failed: ${error.message}`);
}

export async function POST(req: NextRequest) {
  const signature = req.headers.get('stripe-signature');
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET?.trim();
  if (!signature || !webhookSecret) {
    return NextResponse.json({ error: 'Stripe webhook is not configured' }, { status: 400 });
  }

  const rawBody = await req.text();
  let event: Stripe.Event;
  try {
    // Stripe signs the exact raw payload; parsing JSON before this point would
    // invalidate signature verification.
    event = stripe.webhooks.constructEvent(rawBody, signature, webhookSecret);
  } catch (error) {
    console.warn('Stripe webhook signature verification failed', error);
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  try {
    switch (event.type) {
      case 'payment_intent.succeeded':
        await fulfillPayment(event.data.object as Stripe.PaymentIntent);
        break;
      case 'payment_intent.payment_failed':
      case 'payment_intent.canceled':
        await failPayment(event.data.object as Stripe.PaymentIntent);
        break;
      default:
        // Acknowledge unrelated events so Stripe does not retry them.
        break;
    }
    return NextResponse.json({ received: true });
  } catch (error) {
    console.error(`Stripe webhook ${event.id} processing failed`, error);
    // A non-2xx response asks Stripe to retry delivery after transient database
    // failures. All mutations above are idempotent across those retries.
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Webhook processing failed' },
      { status: 500 },
    );
  }
}
