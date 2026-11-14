import { apiFetch } from '@/shared/lib/api';

/**
 * Provider-neutral checkout contract with the web API (`POST /api/checkout/:token`).
 *
 * The server picks the payment provider (web-api/src/lib/payments). The app only opens the hosted payment
 * page it is given, so switching provider (Stripe today, Grow later) needs no app release.
 */
export interface CheckoutSession {
  /** Which provider the server used; informational only. */
  provider?: string;
  checkout_url: string | null;
  session_id: string;
  purchase_id: string;
  /** Integer agorot. */
  amount_ils: number;
  currency: string;
}

export function createCheckout(reelToken: string): Promise<CheckoutSession> {
  return apiFetch<CheckoutSession>(`/api/checkout/${encodeURIComponent(reelToken)}`, { method: 'POST' });
}

/** A hosted payment page is only ever opened over https. */
export function isSafeCheckoutUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  return /^https:\/\/[^\s/?#]+/i.test(url);
}

export function formatIls(agorot: number): string {
  const shekels = agorot / 100;
  return `₪${Number.isInteger(shekels) ? shekels.toFixed(0) : shekels.toFixed(2)}`;
}
