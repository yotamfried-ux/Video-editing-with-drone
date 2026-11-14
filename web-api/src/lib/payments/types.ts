/**
 * Payment provider plugin contract.
 *
 * SportReel sells one thing: a reel, once, through a hosted payment page. Everything specific to a payment
 * company lives behind this interface, in one file under `providers/`. The checkout route, the webhook
 * route, the result route and the mobile app never name a provider.
 *
 * To add a provider (e.g. Grow):
 *   1. Implement `PaymentProvider` in `providers/<id>.ts`.
 *   2. Register it in `registry.ts`.
 *   3. Point the provider's server-to-server notification at `/api/payments/webhook/<id>`.
 *   4. Set `PAYMENT_PROVIDER=<id>` and the provider's own secrets in the server environment.
 * No route, database or mobile change is needed.
 *
 * Rules every provider must keep:
 *   - Fulfilment authority is the verified webhook, never the browser redirect.
 *   - `parseWebhook` must authenticate the notification (signature, or a server-side confirmation call)
 *     before returning anything but `ignored`. A provider that cannot authenticate must throw.
 *   - Amounts are integer agorot (1/100 ILS).
 */

export type ProviderId = string;

export interface CheckoutRequest {
  /** Our purchase row id. The provider must echo it back in the webhook. */
  purchaseId: string;
  reelId: string;
  /** Public reel token (for the cancel page). */
  token: string;
  /** Integer agorot. */
  amount: number;
  currency: 'ils';
  productName: string;
  description: string;
  /** Origin of this deployment, no trailing slash. The provider builds its own return URLs from it. */
  baseUrl: string;
}

export interface CheckoutSession {
  /** Hosted payment page the customer is sent to. */
  url: string;
  /** The provider's id for this checkout; stored on the purchase and matched again in the webhook. */
  sessionId: string;
}

export type PaymentEvent =
  | {
      type: 'paid';
      purchaseId: string;
      reelId: string;
      sessionId: string;
      /** The provider's payment/transaction reference, when it has one. */
      paymentReference: string | null;
      customerEmail: string | null;
    }
  | { type: 'expired'; purchaseId: string; sessionId: string }
  | { type: 'ignored' };

export interface WebhookRequest {
  rawBody: string;
  headers: Headers;
}

export interface SessionStatus {
  /** True only when the provider itself confirms the money moved. */
  paid: boolean;
  purchaseId: string;
  reelId: string;
  sessionId: string;
}

export interface PaymentProvider {
  readonly id: ProviderId;
  /** True when every secret this provider needs is present. An unconfigured provider is never used. */
  isConfigured(): boolean;
  createCheckout(request: CheckoutRequest): Promise<CheckoutSession>;
  /** Authenticate and translate a provider notification. Throw `WebhookAuthError` when it cannot be trusted. */
  parseWebhook(request: WebhookRequest): Promise<PaymentEvent>;
  /** Ask the provider about a checkout it created; null when it does not know the id. */
  getSessionStatus(sessionId: string): Promise<SessionStatus | null>;
}

export class WebhookAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WebhookAuthError';
  }
}

export class PaymentProviderNotConfiguredError extends Error {
  constructor(id: ProviderId) {
    super(`Payment provider "${id}" is not configured`);
    this.name = 'PaymentProviderNotConfiguredError';
  }
}
