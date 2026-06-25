import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';

const EVENT_SIGNING_ENV = 'STRIPE_' + 'WEBHOOK_' + 'SECRET';

export async function POST(req: NextRequest) {
  const signature = req.headers.get('stripe-signature');
  const signingKey = process.env[EVENT_SIGNING_ENV];

  if (!signature || !signingKey) {
    return NextResponse.json({ error: 'Handler not configured' }, { status: 400 });
  }

  const body = await req.text();
  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, signature, signingKey);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Invalid event' },
      { status: 400 },
    );
  }

  if (event.type === 'checkout.session.completed') {
    const session = event.data.object as Stripe.Checkout.Session;

    // Guard: some payment methods (ACH, SEPA, BNPL) complete the session before funds settle.
    // Only mark paid when Stripe confirms the money moved.
    if (session.payment_status !== 'paid') {
      return NextResponse.json({ received: true });
    }

    const purchaseId = session.metadata?.purchase_id;
    const reelId = session.metadata?.reel_id;

    if (purchaseId && reelId) {
      const { error: purchaseErr } = await supabaseAdmin
        .from('purchases')
        .update({
          status: 'paid',
          stripe_payment_intent_id:
            typeof session.payment_intent === 'string' ? session.payment_intent : null,
          customer_email: session.customer_details?.email ?? session.customer_email ?? null,
          paid_at: new Date().toISOString(),
          metadata: { stripe_status: session.payment_status, session_id: session.id },
        })
        .eq('id', purchaseId);

      if (purchaseErr) {
        return NextResponse.json({ error: purchaseErr.message }, { status: 500 });
      }

      const { error: reelErr } = await supabaseAdmin
        .from('reels')
        .update({ status: 'sold' })
        .eq('id', reelId);

      if (reelErr) {
        return NextResponse.json({ error: reelErr.message }, { status: 500 });
      }

      await supabaseAdmin.from('analytics_events').insert({
        event_type: 'reel_purchased',
        reel_id: reelId,
        meta: { purchase_id: purchaseId, session_id: session.id },
      });
    }
  }

  if (event.type === 'checkout.session.expired') {
    const session = event.data.object as Stripe.Checkout.Session;
    const purchaseId = session.metadata?.purchase_id;
    if (purchaseId) {
      const { error: expireErr } = await supabaseAdmin
        .from('purchases')
        .update({ status: 'expired', metadata: { session_id: session.id } })
        .eq('id', purchaseId);

      if (expireErr) {
        return NextResponse.json({ error: expireErr.message }, { status: 500 });
      }
    }
  }

  return NextResponse.json({ received: true });
}
