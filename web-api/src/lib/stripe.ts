import Stripe from 'stripe';

// Lazy singleton: avoids constructing Stripe at import time (build) when the
// secret key is absent. apiVersion is intentionally omitted so the SDK uses
// the version pinned to the account, decoupling us from SDK version bumps.
let _stripe: Stripe | null = null;

function client(): Stripe {
  if (!_stripe) {
    _stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
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
