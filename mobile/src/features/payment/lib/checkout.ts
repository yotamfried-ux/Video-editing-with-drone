import { apiFetch } from '@/shared/lib/api';
import { accessToken } from '@/shared/lib/authedFetch';

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

export async function createCheckout(reelToken: string): Promise<CheckoutSession> {
  // A signed-in buyer is recorded with the purchase, so the app can show it as theirs and let them follow
  // the athlete. Checkout still works signed out.
  const token = await accessToken();
  return apiFetch<CheckoutSession>(`/api/checkout/${encodeURIComponent(reelToken)}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
}

export { formatIls, isSafeCheckoutUrl } from './checkoutFormat';
