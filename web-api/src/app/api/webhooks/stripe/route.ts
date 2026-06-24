import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { sendPaymentConfirmEmail } from '@/lib/email';

export async function POST(req: NextRequest) {
  const sig = req.headers.get('stripe-signature')!;
  const body = await req.text();

  let event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  if (event.type === 'payment_intent.succeeded') {
    const intent = event.data.object;
    const reelId = intent.metadata?.reel_id;
    if (!reelId) return NextResponse.json({ ok: true });

    await supabaseAdmin.from('payments')
      .update({ status: 'completed', paid_at: new Date().toISOString() })
      .eq('stripe_payment_intent_id', intent.id);

    await supabaseAdmin.from('reels')
      .update({ status: 'sold' })
      .eq('id', reelId);

    const { data: reel } = await supabaseAdmin
      .from('reels')
      .select('sport, recording_date, matched_athlete')
      .eq('id', reelId)
      .single();

    if (reel?.matched_athlete) {
      const { data: profile } = await supabaseAdmin
        .from('athlete_profiles')
        .select('email')
        .eq('id', reel.matched_athlete)
        .single();
      if (profile?.email) {
        sendPaymentConfirmEmail(profile.email, reelId, intent.amount).catch(() => {});
      }
    }

    await supabaseAdmin.from('analytics_events').insert({
      event_type: 'payment_completed',
      reel_id: reelId,
      sport: reel?.sport,
      recording_date: reel?.recording_date,
      revenue_ils: intent.amount,
    });
  }

  return NextResponse.json({ ok: true });
}

export const config = { api: { bodyParser: false } };
