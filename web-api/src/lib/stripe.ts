import Stripe from 'stripe';

// Lazy singleton: avoids constructing Stripe at import time during builds when
// the secret key is intentionally absent. Request-level idempotency keys remain
// mandatory for mutations; maxNetworkRetries only protects transient transport
// failures inside stripe-node.
let stripeClient: Stripe | null = null;

function client(): Stripe {
  if (!stripeClient) {
    const secretKey = process.env.STRIPE_SECRET_KEY?.trim();
    if (!secretKey) throw new Error('STRIPE_SECRET_KEY not configured');
    stripeClient = new Stripe(secretKey, {
      maxNetworkRetries: 2,
      timeout: 20_000,
      appInfo: {
        name: 'SportReel',
        version: '1.0.0',
      },
    });
  }
  return stripeClient;
}

export const stripe = new Proxy({} as Stripe, {
  get(_target, property) {
    const instance = client();
    const value = (instance as unknown as Record<string | symbol, unknown>)[property];
    return typeof value === 'function' ? value.bind(instance) : value;
  },
});
