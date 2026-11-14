import { NextRequest, NextResponse } from 'next/server';
import { DEFAULT_PROVIDER_ID, findProvider } from '@/lib/payments/registry';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';

export async function GET(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'checkout-result', 30, 60);
  if (limited) return limited;

  const sessionId = req.nextUrl.searchParams.get('session_id');
  if (!sessionId || sessionId.length > 200) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  // Links issued before the plugin layer carry no provider; they are Stripe sessions.
  const provider = findProvider(req.nextUrl.searchParams.get('provider') || DEFAULT_PROVIDER_ID);
  if (!provider || !provider.isConfigured()) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const session = await provider.getSessionStatus(sessionId).catch(() => null);
  if (!session) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const { purchaseId, reelId } = session;

  const { data: purchase } = await supabaseAdmin
    .from('purchases')
    .select('id,reel_id,status,stripe_checkout_session_id')
    .eq('id', purchaseId)
    .eq('reel_id', reelId)
    .eq('stripe_checkout_session_id', session.sessionId)
    .single();

  if (!purchase) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  // The webhook/database transition remains the fulfillment authority.
  // A paid provider session alone must never grant delivery before our webhook has persisted it.
  if (!session.paid || purchase.status !== 'paid') {
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
