import { NextRequest, NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';

export async function GET(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout-result', 30, 60);
  if (limited) return limited;

  const sessionId = req.nextUrl.searchParams.get('session_id');
  if (!sessionId || !sessionId.startsWith('cs_')) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  let session;
  try {
    session = await stripe.checkout.sessions.retrieve(sessionId);
  } catch {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const purchaseId = session.metadata?.purchase_id;
  const reelId = session.metadata?.reel_id;
  if (!purchaseId || !reelId) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const { data: purchase } = await supabaseAdmin
    .from('purchases')
    .select('id,reel_id,status,stripe_checkout_session_id')
    .eq('id', purchaseId)
    .eq('reel_id', reelId)
    .eq('stripe_checkout_session_id', session.id)
    .single();

  if (!purchase) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  // The webhook/database transition remains the fulfillment authority.
  // A paid Stripe Session alone must never grant delivery before our webhook has persisted it.
  if (session.payment_status !== 'paid' || purchase.status !== 'paid') {
    return NextResponse.json({ status: purchase.status, paid: false });
  }

  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('storage_path,status')
    .eq('id', reelId)
    .single();

  if (!reel?.storage_path || reel.status !== 'sold') {
    return NextResponse.json({ status: purchase.status, paid: true, delivery_ready: false });
  }

  const { data: signed } = await supabaseAdmin.storage
    .from('reels')
    .createSignedUrl(reel.storage_path, 900);

  if (!signed?.signedUrl) {
    return NextResponse.json({ error: 'Could not generate download URL' }, { status: 500 });
  }

  return NextResponse.json({
    status: 'paid',
    paid: true,
    delivery_ready: true,
    download_url: signed.signedUrl,
    expires_in: 900,
  });
}
