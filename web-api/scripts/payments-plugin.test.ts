/**
 * Payment plugin layer: provider selection fails closed, the Stripe plugin authenticates its webhook, and
 * fulfilment is provider-independent and idempotent.
 *
 * Run: npx -y tsx --test scripts/payments-plugin.test.ts   (from web-api/)
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import Stripe from 'stripe';

process.env.STRIPE_SECRET_KEY = 'sk_' + 'test_placeholder';
process.env.STRIPE_WEBHOOK_SECRET = 'plugin_test_signing_secret_not_used_in_production';

import { applyPaymentEvent, type PurchaseStore } from '../src/lib/payments/fulfillment';
import { growProvider } from '../src/lib/payments/providers/grow';
import { stripeProvider } from '../src/lib/payments/providers/stripe';
import { activeProvider, findProvider, requireProvider } from '../src/lib/payments/registry';
import {
  PaymentProviderNotConfiguredError,
  WebhookAuthError,
  type PaymentEvent,
} from '../src/lib/payments/types';

const PURCHASE = '00000000-0000-4000-8000-000000000001';
const REEL = '00000000-0000-4000-8000-000000000002';

function fakeStore(rows: Record<string, { status: string; sessionId: string; reelId: string }>) {
  const calls: string[] = [];
  const store: PurchaseStore = {
    async markPaid({ purchaseId, reelId, sessionId }) {
      const row = rows[purchaseId];
      if (!row || row.reelId !== reelId || row.sessionId !== sessionId || row.status !== 'checkout_created') return false;
      row.status = 'paid';
      calls.push('paid');
      return true;
    },
    async markReelSold() { calls.push('sold'); },
    async markExpired({ purchaseId, sessionId }) {
      const row = rows[purchaseId];
      if (row && row.sessionId === sessionId && row.status === 'checkout_created') { row.status = 'expired'; calls.push('expired'); }
    },
    async recordPurchaseEvent() { calls.push('event'); },
  };
  return { store, calls, rows };
}

function signedStripeRequest(event: object, secret = process.env.STRIPE_WEBHOOK_SECRET!) {
  const rawBody = JSON.stringify(event);
  const header = new Stripe('sk_' + 'test_placeholder').webhooks.generateTestHeaderString({ payload: rawBody, secret });
  return { rawBody, headers: new Headers({ 'stripe-signature': header }) };
}

const completed = (paymentStatus: string) => ({
  id: 'evt_plugin', object: 'event', type: 'checkout.session.completed',
  data: { object: { id: 'cs_test_plugin', object: 'checkout.session', payment_status: paymentStatus,
    payment_intent: 'pi_plugin', customer_details: { email: 'buyer@example.com' },
    metadata: { purchase_id: PURCHASE, reel_id: REEL } } },
});

test('the active provider defaults to Stripe and a bad selection fails closed', () => {
  delete process.env.PAYMENT_PROVIDER;
  assert.equal(activeProvider().id, 'stripe');
  process.env.PAYMENT_PROVIDER = 'Stripe ';
  assert.equal(activeProvider().id, 'stripe');
  for (const bad of ['grow', 'paypal', '__proto__', 'constructor']) {
    process.env.PAYMENT_PROVIDER = bad;
    assert.throws(() => activeProvider(), PaymentProviderNotConfiguredError, bad);
  }
  delete process.env.PAYMENT_PROVIDER;
});

test('Grow is registered as a placeholder that no customer can reach', async () => {
  assert.equal(findProvider('grow'), growProvider);
  assert.equal(growProvider.isConfigured(), false);
  assert.throws(() => requireProvider('grow'), PaymentProviderNotConfiguredError);
  await assert.rejects(growProvider.parseWebhook({ rawBody: '{}', headers: new Headers() }), PaymentProviderNotConfiguredError);
  assert.equal(findProvider('unknown'), null);
  assert.equal(findProvider('toString'), null);
});

test('Stripe plugin: a signed paid event becomes a provider-neutral paid event', async () => {
  const event = await stripeProvider.parseWebhook(signedStripeRequest(completed('paid')));
  assert.deepEqual(event, {
    type: 'paid', purchaseId: PURCHASE, reelId: REEL, sessionId: 'cs_test_plugin',
    paymentReference: 'pi_plugin', customerEmail: 'buyer@example.com',
  });
});

test('Stripe plugin: unsigned, wrongly signed and unsettled events grant nothing', async () => {
  await assert.rejects(stripeProvider.parseWebhook({ rawBody: JSON.stringify(completed('paid')), headers: new Headers() }), WebhookAuthError);
  await assert.rejects(stripeProvider.parseWebhook(signedStripeRequest(completed('paid'), 'another_secret')), WebhookAuthError);
  assert.deepEqual(await stripeProvider.parseWebhook(signedStripeRequest(completed('unpaid'))), { type: 'ignored' });
  assert.deepEqual(await stripeProvider.parseWebhook(signedStripeRequest({ ...completed('paid'), type: 'charge.refunded' })), { type: 'ignored' });
  assert.equal(await stripeProvider.getSessionStatus('not-a-stripe-session'), null);
});

test('fulfilment: first paid event sells the reel once; a replay does nothing', async () => {
  const { store, calls, rows } = fakeStore({ [PURCHASE]: { status: 'checkout_created', sessionId: 'sess_1', reelId: REEL } });
  const paid: PaymentEvent = { type: 'paid', purchaseId: PURCHASE, reelId: REEL, sessionId: 'sess_1', paymentReference: null, customerEmail: null };
  assert.deepEqual(await applyPaymentEvent(paid, 'any-provider', store), { received: true });
  assert.deepEqual(calls, ['paid', 'sold', 'event']);
  assert.deepEqual(await applyPaymentEvent(paid, 'any-provider', store), { received: true, duplicate: true });
  assert.deepEqual(calls, ['paid', 'sold', 'event']);
  assert.equal(rows[PURCHASE].status, 'paid');
});

test('fulfilment: a paid event for another session or reel sells nothing; expiry never undoes a payment', async () => {
  const { store, calls, rows } = fakeStore({ [PURCHASE]: { status: 'checkout_created', sessionId: 'sess_1', reelId: REEL } });
  const base = { type: 'paid' as const, purchaseId: PURCHASE, reelId: REEL, sessionId: 'sess_1', paymentReference: null, customerEmail: null };
  assert.deepEqual(await applyPaymentEvent({ ...base, sessionId: 'sess_other' }, 'p', store), { received: true, duplicate: true });
  assert.deepEqual(await applyPaymentEvent({ ...base, reelId: 'other-reel' }, 'p', store), { received: true, duplicate: true });
  assert.deepEqual(calls, []);
  await applyPaymentEvent(base, 'p', store);
  await applyPaymentEvent({ type: 'expired', purchaseId: PURCHASE, sessionId: 'sess_1' }, 'p', store);
  assert.equal(rows[PURCHASE].status, 'paid');
  assert.deepEqual(await applyPaymentEvent({ type: 'ignored' }, 'p', store), { received: true });
});
