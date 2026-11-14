import {
  type CheckoutRequest,
  type CheckoutSession,
  type PaymentEvent,
  type PaymentProvider,
  type SessionStatus,
  type WebhookRequest,
  PaymentProviderNotConfiguredError,
} from '../types';

/**
 * Grow (formerly Meshulam) — placeholder plugin.
 *
 * Registered so that selecting it is one environment change once it is implemented, and so the routes,
 * webhook URL (`/api/payments/webhook/grow`) and tests already cover a second provider.
 *
 * NOT IMPLEMENTED on purpose: the request/response fields, the notification format and the way a
 * notification is authenticated must come from the merchant's own Grow API documentation and sandbox
 * credentials. They are not guessed here. Until then `isConfigured()` is false, so the registry refuses
 * to use it and no customer can reach it.
 *
 * To implement, fill the three methods and make `isConfigured()` check the Grow secrets
 * (suggested names: GROW_USER_ID, GROW_PAGE_CODE, GROW_API_KEY, GROW_API_BASE_URL):
 *   - createCheckout: create the payment page for `request.amount` agorot, pass `request.purchaseId` and
 *     `request.reelId` in the provider's custom fields, return its page URL and process id.
 *   - parseWebhook: authenticate the notification (signature or a server-side confirmation call to Grow),
 *     throw WebhookAuthError when it cannot be trusted, then return `paid` with the custom fields.
 *   - getSessionStatus: query Grow for the process id; `paid` only when Grow says the charge succeeded.
 */
export const growProvider: PaymentProvider = {
  id: 'grow',

  isConfigured() {
    return false;
  },

  async createCheckout(_request: CheckoutRequest): Promise<CheckoutSession> {
    throw new PaymentProviderNotConfiguredError('grow');
  },

  async parseWebhook(_request: WebhookRequest): Promise<PaymentEvent> {
    throw new PaymentProviderNotConfiguredError('grow');
  },

  async getSessionStatus(_sessionId: string): Promise<SessionStatus | null> {
    throw new PaymentProviderNotConfiguredError('grow');
  },
};
