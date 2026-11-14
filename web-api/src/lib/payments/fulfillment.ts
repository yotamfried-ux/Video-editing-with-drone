import type { PaymentEvent, ProviderId } from './types';

/**
 * Provider-independent purchase transitions. The store is an interface so the rules below are tested
 * without a database (web-api/scripts/payments-plugin.test.ts).
 */
export interface PurchaseStore {
  /**
   * checkout_created -> paid, only for the row that matches purchase, reel and the provider's session id.
   * Returns false when no row made that transition (replay, unknown ids, already paid).
   */
  markPaid(input: {
    purchaseId: string;
    reelId: string;
    sessionId: string;
    paymentReference: string | null;
    customerEmail: string | null;
    provider: ProviderId;
  }): Promise<boolean>;
  markReelSold(reelId: string): Promise<void>;
  /** checkout_created -> expired for the matching row; a paid purchase is never expired. */
  markExpired(input: { purchaseId: string; sessionId: string; provider: ProviderId }): Promise<void>;
  recordPurchaseEvent(input: { purchaseId: string; reelId: string; sessionId: string; provider: ProviderId }): Promise<void>;
}

export type FulfillmentResult = { received: true; duplicate?: true };

export async function applyPaymentEvent(
  event: PaymentEvent,
  provider: ProviderId,
  store: PurchaseStore,
): Promise<FulfillmentResult> {
  if (event.type === 'paid') {
    const transitioned = await store.markPaid({ ...event, provider });
    // Providers retry notifications. Only the first valid checkout_created -> paid transition may run the
    // downstream side effects.
    if (!transitioned) return { received: true, duplicate: true };
    await store.markReelSold(event.reelId);
    await store.recordPurchaseEvent({
      purchaseId: event.purchaseId,
      reelId: event.reelId,
      sessionId: event.sessionId,
      provider,
    });
    return { received: true };
  }
  if (event.type === 'expired') {
    await store.markExpired({ purchaseId: event.purchaseId, sessionId: event.sessionId, provider });
  }
  return { received: true };
}
