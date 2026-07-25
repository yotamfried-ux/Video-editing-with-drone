import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { stripe } from '@/lib/stripe';
import { ilsToMinorUnits } from '@/lib/pricing';

const PUBLIC_ID_RE = /^[A-Za-z0-9_-]{8,80}$/;

type PricingRow = { sport: string; price_ils: number | string };

function baseUrl(): string {
  const domain = process.env.NEXT_PUBLIC_APP_DOMAIN || process.env.APP_DOMAIN;
  if (!domain) return 'http://localhost:3001';
  return domain.startsWith('http://') || domain.startsWith('https://')
    ? domain.replace(/\/$/, '')
    : `https://${domain.replace(/\/$/, '')}`;
}

async function getPriceMinor(sport: string | null): Promise<number> {
  const normalized = (sport || 'default').toLowerCase();
  const { data, error } = await supabaseAdmin
    .from('pricing')
    .select('sport, price_ils')
    .in('sport', [normalized, 'default'])
    .returns<PricingRow[]>();

  if (error) throw new Error(error.message);
  const exact = data?.find((row) => row.sport === normalized);
  const fallback = data?.find((row) => row.sport === 'default');
  const majorIls = exact?.price_ils ?? fallback?.price_ils;
  if (majorIls === undefined) throw new Error(`No positive price configured for ${normalized}`);
  return ilsToMinorUnits(majorIls);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const limited = await enforceRateLimit(req, 'checkout-create', 20, 60);
  if (limited) return limited;

  const { token } = await params;
  if (!PUBLIC_ID_RE.test(token)) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const { data: reel, error } = await supabaseAdmin
    .from('reels')
    .select('id, token, sport, athlete_desc, status, expires_at, storage_path')
    .eq('token', token)
    .single();

  if (error || !reel) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (reel.status === 'sold') {
    return NextResponse.json({ error: 'This clip was already sold' }, { status: 409 });
  }
  if (reel.status === 'expired' || !reel.expires_at || new Date(reel.expires_at) < new Date()) {
    return NextResponse.json({ error: 'This clip has expired' }, { status: 410 });
  }
  if (!reel.storage_path) {
    return NextResponse.json({ error: 'File not available' }, { status: 404 });
  }

  try {
    const amountMinor = await getPriceMinor(reel.sport);
    const { data: purchase, error: purchaseError } = await supabaseAdmin
      .from('purchases')
      .insert({
        reel_id: reel.id,
        token,
        status: 'checkout_created',
        amount_ils: amountMinor,
        currency: 'ils',
        metadata: { source: 'discover', amount_unit: 'agorot' },
      })
      .select('id')
      .single();

    if (purchaseError || !purchase) {
      throw new Error(purchaseError?.message ?? 'Could not create purchase');
    }

    const session = await stripe.checkout.sessions.create({
      mode: 'payment',
      client_reference_id: reel.id,
      line_items: [
        {
          quantity: 1,
          price_data: {
            currency: 'ils',
            unit_amount: amountMinor,
            product_data: {
              name: `${reel.sport || 'Sport'} reel`,
              description: reel.athlete_desc || 'SportReel clip purchase',
            },
          },
        },
      ],
      metadata: { purchase_id: purchase.id, reel_id: reel.id, token },
      success_url: `${baseUrl()}/checkout/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${baseUrl()}/checkout/cancel?token=${encodeURIComponent(token)}`,
    });

    const { error: updateError } = await supabaseAdmin
      .from('purchases')
      .update({ stripe_checkout_session_id: session.id })
      .eq('id', purchase.id);
    if (updateError) throw new Error(updateError.message);

    return NextResponse.json({
      checkout_url: session.url,
      session_id: session.id,
      purchase_id: purchase.id,
      amount_ils: amountMinor,
      currency: 'ils',
    });
  } catch (checkoutError) {
    return NextResponse.json(
      { error: checkoutError instanceof Error ? checkoutError.message : 'Could not create checkout' },
      { status: 502 },
    );
  }
}
