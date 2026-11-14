import { supabaseAdmin } from '@/lib/supabase-admin';
import type { PurchaseStore } from './fulfillment';

/**
 * `purchases.stripe_checkout_session_id` / `stripe_payment_intent_id` predate the plugin layer. They hold
 * the active provider's session id and payment reference whatever the provider; `metadata.provider` says
 * which one. Renaming the columns needs a migration and is deliberately not part of this change.
 */
export const supabasePurchaseStore: PurchaseStore = {
  async markPaid({ purchaseId, reelId, sessionId, paymentReference, customerEmail, provider }) {
    const { data, error } = await supabaseAdmin
      .from('purchases')
      .update({
        status: 'paid',
        stripe_payment_intent_id: paymentReference,
        customer_email: customerEmail,
        paid_at: new Date().toISOString(),
        metadata: { provider, provider_status: 'paid', session_id: sessionId },
      })
      .eq('id', purchaseId)
      .eq('reel_id', reelId)
      .eq('stripe_checkout_session_id', sessionId)
      .eq('status', 'checkout_created')
      .select('id')
      .maybeSingle();
    if (error) throw new Error(error.message);
    return Boolean(data);
  },

  async markReelSold(reelId) {
    const { error } = await supabaseAdmin.from('reels').update({ status: 'sold' }).eq('id', reelId);
    if (error) throw new Error(error.message);
  },

  async markExpired({ purchaseId, sessionId, provider }) {
    const { error } = await supabaseAdmin
      .from('purchases')
      .update({ status: 'expired', metadata: { provider, session_id: sessionId } })
      .eq('id', purchaseId)
      .eq('stripe_checkout_session_id', sessionId)
      .eq('status', 'checkout_created');
    if (error) throw new Error(error.message);
  },

  async recordPurchaseEvent({ purchaseId, reelId, sessionId, provider }) {
    await supabaseAdmin.from('analytics_events').insert({
      event_type: 'reel_purchased',
      reel_id: reelId,
      meta: { purchase_id: purchaseId, session_id: sessionId, provider },
    });
  },
};
