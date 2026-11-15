import { growProvider } from './providers/grow';
import { stripeProvider } from './providers/stripe';
import { type PaymentProvider, type ProviderId, PaymentProviderNotConfiguredError } from './types';

const PROVIDERS: Record<ProviderId, PaymentProvider> = {
  [stripeProvider.id]: stripeProvider,
  [growProvider.id]: growProvider,
};

export const DEFAULT_PROVIDER_ID: ProviderId = 'stripe';

/** A registered provider by id, whether or not it is configured; null for an unknown id. */
export function findProvider(id: string | null | undefined): PaymentProvider | null {
  if (!id) return null;
  return Object.prototype.hasOwnProperty.call(PROVIDERS, id) ? PROVIDERS[id] : null;
}

/** A registered and configured provider; throws otherwise. Used for webhooks and result lookups. */
export function requireProvider(id: string): PaymentProvider {
  const provider = findProvider(id);
  if (!provider || !provider.isConfigured()) throw new PaymentProviderNotConfiguredError(id);
  return provider;
}

/**
 * The one provider new checkouts use: `PAYMENT_PROVIDER`, default Stripe.
 * A misconfigured value fails closed instead of silently falling back to another payment company.
 */
export function activeProvider(): PaymentProvider {
  const id = (process.env.PAYMENT_PROVIDER || DEFAULT_PROVIDER_ID).trim().toLowerCase();
  return requireProvider(id);
}
