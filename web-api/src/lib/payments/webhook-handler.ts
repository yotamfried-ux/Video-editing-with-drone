import { NextRequest, NextResponse } from 'next/server';
import { applyPaymentEvent } from './fulfillment';
import { findProvider } from './registry';
import { supabasePurchaseStore } from './supabase-purchase-store';
import { PaymentProviderNotConfiguredError, WebhookAuthError } from './types';

/** One webhook implementation for every provider; the route only says which provider it is for. */
export async function handlePaymentWebhook(req: NextRequest, providerId: string): Promise<NextResponse> {
  const provider = findProvider(providerId);
  if (!provider || !provider.isConfigured()) {
    return NextResponse.json({ error: 'Handler not configured' }, { status: 400 });
  }

  const rawBody = await req.text();
  let event;
  try {
    event = await provider.parseWebhook({ rawBody, headers: req.headers });
  } catch (err) {
    if (err instanceof WebhookAuthError || err instanceof PaymentProviderNotConfiguredError) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    return NextResponse.json({ error: 'Invalid event' }, { status: 400 });
  }

  try {
    return NextResponse.json(await applyPaymentEvent(event, provider.id, supabasePurchaseStore));
  } catch (err) {
    // A 5xx makes the provider retry; the paid transition is idempotent.
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Fulfilment failed' }, { status: 500 });
  }
}
