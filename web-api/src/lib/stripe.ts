import Stripe from 'stripe';

// Lazy singleton: avoids constructing Stripe at import time (build) when the
// secret key is absent. apiVersion is intentionally omitted so the SDK uses
// the version pinned to the account, decoupling us from SDK version bumps.
let _stripe: Stripe | null = null;

function client(): Stripe {
  if (!_stripe) {
    // Tests point the SDK at a local fake (NODE_ENV=test only); production always talks to Stripe.
    const testHost = process.env.NODE_ENV === 'test' ? process.env.STRIPE_TEST_API_HOST : undefined;
    _stripe = testHost
      ? new Stripe(process.env.STRIPE_SECRET_KEY!, {
          host: testHost,
          port: Number(process.env.STRIPE_TEST_API_PORT),
          protocol: 'http',
          maxNetworkRetries: 0,
        })
      : new Stripe(process.env.STRIPE_SECRET_KEY!);
  }
  return _stripe;
}

export const stripe = new Proxy({} as Stripe, {
  get(_target, prop) {
    const c = client();
    const value = (c as unknown as Record<string | symbol, unknown>)[prop];
    return typeof value === 'function' ? value.bind(c) : value;
  },
});
