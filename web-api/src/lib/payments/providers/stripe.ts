import type Stripe from 'stripe';
import { stripe } from '@/lib/stripe';
import {
  type CheckoutRequest,
  type CheckoutSession,
  type PaymentEvent,
  type PaymentProvider,
  type SessionStatus,
  type WebhookRequest,
  WebhookAuthError,
} from '../types';

const EVENT_SIGNING_ENV = 'STRIPE_' + 'WEBHOOK_' + 'SECRET';

export const stripeProvider: PaymentProvider = {
  id: 'stripe',

  isConfigured() {
    return Boolean(process.env.STRIPE_SECRET_KEY);
  },

  async createCheckout(request: CheckoutRequest): Promise<CheckoutSession> {
    const session = await stripe.checkout.sessions.create({
      mode: 'payment',
      client_reference_id: request.reelId,
      line_items: [
        {
          quantity: 1,
          price_data: {
            currency: request.currency,
            unit_amount: request.amount,
            product_data: { name: request.productName, description: request.description },
          },
        },
      ],
      metadata: { purchase_id: request.purchaseId, reel_id: request.reelId, token: request.token },
      success_url: `${request.baseUrl}/checkout/success?provider=stripe&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${request.baseUrl}/checkout/cancel?token=${encodeURIComponent(request.token)}`,
    });
    if (!session.url) throw new Error('Stripe did not return a checkout URL');
    return { url: session.url, sessionId: session.id };
  },

  async parseWebhook({ rawBody, headers }: WebhookRequest): Promise<PaymentEvent> {
    const signature = headers.get('stripe-signature');
    const signingKey = process.env[EVENT_SIGNING_ENV];
    if (!signature || !signingKey) throw new WebhookAuthError('Handler not configured');

    let event: Stripe.Event;
    try {
      event = stripe.webhooks.constructEvent(rawBody, signature, signingKey);
    } catch (err) {
      throw new WebhookAuthError(err instanceof Error ? err.message : 'Invalid event');
    }

    if (event.type === 'checkout.session.completed') {
      const session = event.data.object as Stripe.Checkout.Session;
      // Some payment methods (ACH, SEPA, BNPL) complete the session before funds settle.
      // Only report paid when Stripe confirms the money moved.
      if (session.payment_status !== 'paid') return { type: 'ignored' };
      const purchaseId = session.metadata?.purchase_id;
      const reelId = session.metadata?.reel_id;
      if (!purchaseId || !reelId) return { type: 'ignored' };
      return {
        type: 'paid',
        purchaseId,
        reelId,
        sessionId: session.id,
        paymentReference: typeof session.payment_intent === 'string' ? session.payment_intent : null,
        customerEmail: session.customer_details?.email ?? session.customer_email ?? null,
      };
    }

    if (event.type === 'checkout.session.expired') {
      const session = event.data.object as Stripe.Checkout.Session;
      const purchaseId = session.metadata?.purchase_id;
      if (!purchaseId) return { type: 'ignored' };
      return { type: 'expired', purchaseId, sessionId: session.id };
    }

    return { type: 'ignored' };
  },

  async getSessionStatus(sessionId: string): Promise<SessionStatus | null> {
    if (!sessionId.startsWith('cs_')) return null;
    let session: Stripe.Checkout.Session;
    try {
      session = await stripe.checkout.sessions.retrieve(sessionId);
    } catch {
      return null;
    }
    const purchaseId = session.metadata?.purchase_id;
    const reelId = session.metadata?.reel_id;
    if (!purchaseId || !reelId) return null;
    return { paid: session.payment_status === 'paid', purchaseId, reelId, sessionId: session.id };
  },
};
