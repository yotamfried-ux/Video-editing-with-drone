# Stripe mobile payment — official reference audit

Date: 2026-07-21  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Branch: `audit/end-to-end-hardening-20260721`  
Status: **official-reference implementation complete; CI, migration, deployment, store-policy decision, and real test payment pending**

## 1. Scope

This audit covers the in-app Stripe card-payment path:

```text
SportReel React Native checkout
→ Next.js server creates a PaymentIntent
→ Stripe PaymentSheet collects/confirms payment
→ signed Stripe webhook validates and fulfills the purchase
→ Supabase marks payment/reel state
→ mobile polls durable fulfillment state
→ completed payment unlocks a short-lived download URL
```

The implementation is adapted from Stripe-owned repositories. It does not copy a third-party tutorial or let the mobile client decide price, fulfillment, or ownership.

## 2. Official GitHub sources

### 2.1 React Native PaymentSheet

Repository: `stripe/stripe-react-native`

- SDK and Expo/provider guidance:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/README.md
- Complete PaymentSheet example:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/example/src/screens/PaymentsUICompleteScreen.tsx
- Expo config plugin behavior:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/src/plugin/withStripe.ts

Patterns adopted:

- configure `StripeProvider` once at the app root;
- provide a redirect URL scheme for 3DS/bank redirects;
- fetch a PaymentIntent client secret from the server;
- call `initPaymentSheet` before `presentPaymentSheet`;
- handle canceled, failed, and timed-out presentation explicitly;
- never collect raw card numbers through SportReel code.

### 2.2 Server-side PaymentIntent creation

Repository: `stripe-samples/accept-a-payment`

- Official Next.js PaymentIntent route:  
  https://github.com/stripe-samples/accept-a-payment/blob/a562e27f6fd2045d8c1bfb6744dab24a755f1777/payment-element/server/nextjs/app/api/create-payment-intent/route.ts

Patterns adopted:

- amount and currency are owned by the server;
- the server returns only the `client_secret` needed by PaymentSheet;
- `automatic_payment_methods: { enabled: true }` lets Stripe choose eligible methods from Dashboard/account configuration;
- errors return a non-success HTTP response.

SportReel additionally uses a stable client checkout-session ID as a Stripe idempotency key, because mobile retries and repeated taps must not create duplicate PaymentIntents.

### 2.3 Signed webhook processing

Repository: `stripe/stripe-node`

- Official raw-body webhook-signing example:  
  https://github.com/stripe/stripe-node/blob/dea3ce7ecdf7fe3ae9d68391b9512075db521ef7/examples/webhook-signing/express/main.ts

Patterns adopted:

- read the exact raw request body;
- verify `Stripe-Signature` with `stripe.webhooks.constructEvent`;
- fulfill on `payment_intent.succeeded`, not on a client navigation event;
- acknowledge unrelated event types;
- return non-2xx on processing failure so Stripe retries delivery.

### 2.4 Stripe CLI testing

Repository: `stripe/stripe-cli`

- Listen/forward official workflow:  
  https://github.com/stripe/stripe-cli/wiki/listen-command
- Trigger official test events:  
  https://github.com/stripe/stripe-cli/wiki/trigger-command

These commands validate signature delivery and retry behavior. A real SportReel test-mode PaymentSheet purchase is still required for metadata/amount/database fulfillment because a generic generated event does not contain a real SportReel payment row.

## 3. Critical findings from the pre-audit implementation

### Finding A — price units were inconsistent

The `pricing.price_ils` seed stores human-readable values such as `79`, but Stripe requires amounts in the smallest currency unit. The old server sent `79` directly to Stripe while the mobile UI divided it by 100, risking a charge of ₪0.79 instead of ₪79.

Resolution:

- `pricing.price_ils` remains human-readable major ILS units;
- `getPriceForReel` converts exactly once with `Math.round(value * 100)`;
- `payments.amount_ils` records the Stripe minor-unit amount used for verification;
- analytics revenue converts back to major ILS units.

### Finding B — download tokens could be null

The original database schema declared `download_token` without a default, while the checkout API did not always generate one. A successful payment could therefore reach the app without a usable purchase credential.

Resolution:

- the server explicitly generates a UUID token;
- fresh schema and migration add a UUID default, backfill existing nulls, and enforce `NOT NULL`;
- mobile validates persistence by awaiting secure storage before presenting PaymentSheet.

### Finding C — duplicate PaymentIntents were possible

Repeated taps, transport retries, or an ambiguous mobile response could create multiple PaymentIntents for the same purchase attempt.

Resolution:

- mobile creates one stable `checkout_session_id` per checkout screen instance;
- the server uses it as the Stripe request `idempotencyKey`;
- the unique `stripe_payment_intent_id` row is reused on replay;
- stripe-node has bounded network retries, while request-level idempotency remains mandatory.

### Finding D — the app claimed success before durable fulfillment

The old success screen displayed “Payment confirmed” immediately after PaymentSheet returned without error. That proves client confirmation completed, but it is not durable server fulfillment.

Resolution:

- the mobile app now says “Finalizing payment” first;
- it polls a token-scoped payment-status endpoint;
- only `payments.status='completed'`, written by the signed webhook, displays “Payment confirmed” and enables download;
- failed payments remain locked.

### Finding E — webhook retries could duplicate side effects

The previous webhook updated state and inserted analytics without amount/currency/ownership reconciliation. Re-delivery could duplicate analytics or payment-confirmation email attempts.

Resolution:

- verify PaymentIntent currency, amount, `reel_id`, and durable payment row before fulfillment;
- handle `payment_intent.succeeded`, `payment_intent.payment_failed`, and `payment_intent.canceled`;
- make payment/reel updates idempotent;
- enforce one `(payment_id, event_type)` analytics row;
- use durable receipt-email claim/sent timestamps so retries can recover without intentional duplicate sends;
- await email delivery instead of starting an untracked serverless promise.

### Finding F — in-memory token storage lost purchases after restart

The previous Zustand-only token disappeared after process death or redirect recovery.

Resolution:

- store the bearer token in Expo SecureStore;
- hydrate it when the success screen reopens;
- keep it out of routes, screenshots, logs, and navigation history;
- delete it after a successful download.

## 4. Digital-product store policy blocker

The official `stripe/stripe-react-native` README states that digital products or services unlocked in an app must use the app store's in-app purchase APIs. SportReel currently sells a downloadable digital video.

Therefore the technical Stripe implementation is **blocked from being treated as an App Store / Google Play production payment solution** until one of these product/distribution paths is formally chosen and verified:

1. Apple/Google in-app purchase for the consumer digital video;
2. purchase on the web, with the app acting only as a signed-in viewer/downloader of an externally purchased item;
3. a documented store-policy exception applicable to the exact SportReel product and distribution model;
4. private/enterprise/direct distribution where the consumer-store billing rule does not apply.

Do not enable Apple Pay or Google Pay merely to bypass this decision. Those wallets inside Stripe PaymentSheet do not replace store billing requirements for a digital product.

## 5. Implementation checklist

### Server

- [x] Calculate price from the server-side reel/sport pricing table.
- [x] Convert major ILS to minor units exactly once.
- [x] Create PaymentIntent with `automatic_payment_methods`.
- [x] Attach payer email and SportReel metadata.
- [x] Use a stable Stripe idempotency key.
- [x] Persist a non-null UUID download token.
- [x] Return no secret key or raw payment method data to mobile.
- [x] Enable bounded stripe-node transport retries.

### React Native

- [x] Configure one root `StripeProvider`.
- [x] Configure `sportreel` redirect scheme.
- [x] Call `initPaymentSheet` before `presentPaymentSheet`.
- [x] Handle canceled and failed PaymentSheet results.
- [x] Persist the bearer token in SecureStore.
- [x] Avoid putting the token in navigation URLs.
- [x] Wait for webhook-backed status before success/download.

### Webhook and fulfillment

- [x] Verify the raw-body Stripe signature.
- [x] Validate currency, amount, reel ownership, and payment-row identity.
- [x] Complete payment/reel state only for a valid succeeded intent.
- [x] Persist failed/canceled terminal state.
- [x] Deduplicate analytics events.
- [x] Make receipt email retry-aware.
- [x] Return 500 for retriable processing failure.
- [x] Keep download locked until durable completed state.

### Tests and deployment

- [x] Add `scripts/test_stripe_official_payment_contract.py`.
- [x] Add a dedicated Stripe payment workflow with web/mobile type-checks.
- [ ] Pass the workflow on the final PR head.
- [ ] Review and apply `20260721_harden_payment_download_tokens.sql`.
- [ ] Verify the new columns/default/indexes in live Supabase.
- [ ] Deploy the Web API to Vercel.
- [ ] Publish the mobile JavaScript/native update through the correct EAS path.
- [ ] Execute a Stripe test-mode PaymentSheet purchase.
- [ ] Confirm one PaymentIntent and one payment row after repeated taps/retries.
- [ ] Confirm webhook signature rejection for invalid payloads.
- [ ] Confirm succeeded webhook unlocks exactly one purchase and one analytics row.
- [ ] Confirm failed/canceled payment remains locked.
- [ ] Confirm app restart preserves the secure token and resumes status polling.
- [ ] Confirm download URL expires after 15 minutes.
- [ ] Resolve the App Store / Google Play digital-product billing decision before consumer release.

## 6. Closure rule

This audit is not closed by type-checks or static contracts alone. Closure requires:

- final-head CI green;
- migration applied and live-verified;
- Vercel/EAS deployment verified;
- one real Stripe test-mode purchase through the app;
- webhook, database, email, analytics, restart recovery, and download evidence;
- a documented distribution/payment-policy decision for the digital video product.
