# Stripe mobile payment — official reference audit

Date: 2026-07-21  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Branch: `audit/end-to-end-hardening-20260721`  
Status: **official-reference implementation complete; final CI, migration, deployment, store-policy decision, and real test payment pending**

## 1. Scope

This audit covers the React Native Stripe card-payment path:

```text
SportReel React Native checkout
→ Next.js server calculates the price and creates a PaymentIntent
→ Stripe PaymentSheet collects and confirms payment
→ redirect/deep-link result returns through the Stripe SDK
→ signed Stripe webhook validates and fulfills the purchase
→ Supabase records payment/reel state
→ Stripe sends the payment receipt
→ mobile polls durable fulfillment state
→ completed payment unlocks a short-lived download URL
```

The implementation is adapted from Stripe-owned repositories. It does not use a third-party tutorial, collect raw card numbers, let the mobile client choose the amount, or let a navigation event unlock digital content.

## 2. Official sources

All implementation examples are from Stripe-owned GitHub repositories and pinned to inspected commits. Stripe's official receipt documentation is used only to resolve which system owns the customer receipt.

### 2.1 React Native PaymentSheet

Repository: `stripe/stripe-react-native`  
Inspected commit: `476f9db247c7eec4c75279377fd6af4f0fd2db3c`

- SDK, Expo/provider and digital-goods guidance:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/README.md
- Complete PaymentSheet example:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/example/src/screens/PaymentsUICompleteScreen.tsx
- Redirect/deep-link handling example:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/example/src/screens/HomeScreen.tsx
- PaymentIntent result retrieval example:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/example/src/screens/PaymentResultScreen.tsx
- Expo config plugin behavior:  
  https://github.com/stripe/stripe-react-native/blob/476f9db247c7eec4c75279377fd6af4f0fd2db3c/src/plugin/withStripe.ts

Patterns adopted:

- configure one root `StripeProvider`;
- install Stripe's Expo config plugin;
- provide a redirect URL scheme;
- pass cold-start and live links to `handleURLCallback`;
- fetch a PaymentIntent client secret from the server;
- call `initPaymentSheet` before `presentPaymentSheet`;
- provide known payer email as default billing data;
- handle canceled, failed, and timed-out presentation explicitly;
- never collect raw card numbers through SportReel code.

### 2.2 Server-side PaymentIntent creation

Repository: `stripe-samples/accept-a-payment`  
Inspected commit: `a562e27f6fd2045d8c1bfb6744dab24a755f1777`

- Official Next.js PaymentIntent route:  
  https://github.com/stripe-samples/accept-a-payment/blob/a562e27f6fd2045d8c1bfb6744dab24a755f1777/payment-element/server/nextjs/app/api/create-payment-intent/route.ts
- Official Next.js signed-webhook route:  
  https://github.com/stripe-samples/accept-a-payment/blob/a562e27f6fd2045d8c1bfb6744dab24a755f1777/payment-element/server/nextjs/app/api/webhook/route.ts

Patterns adopted:

- amount and currency are owned by the server;
- Stripe receives an integer amount in the currency's smallest unit;
- `automatic_payment_methods: { enabled: true }` lets Stripe choose eligible methods from Dashboard/account configuration;
- the app receives the PaymentIntent client secret required by PaymentSheet;
- errors return non-success HTTP responses.

SportReel additionally uses a persisted client checkout-attempt ID as the Stripe idempotency key. Repeated taps, app restarts and ambiguous network responses therefore resolve to the same PaymentIntent while that attempt remains pending. The ID is cleared after a webhook-backed terminal result so a later retry creates a new logical attempt.

### 2.3 stripe-node transport and webhook behavior

Repository: `stripe/stripe-node`  
Inspected commit: `dea3ce7ecdf7fe3ae9d68391b9512075db521ef7`

- SDK and retry/request-option guidance:  
  https://github.com/stripe/stripe-node/blob/dea3ce7ecdf7fe3ae9d68391b9512075db521ef7/README.md
- Official Next.js webhook signing example:  
  https://github.com/stripe/stripe-node/blob/dea3ce7ecdf7fe3ae9d68391b9512075db521ef7/examples/webhook-signing/nextjs/app/api/webhooks/route.ts

Patterns adopted:

- read the exact raw request body;
- verify `Stripe-Signature` with `stripe.webhooks.constructEvent`;
- fulfill on `payment_intent.succeeded`, not on a client navigation event;
- acknowledge unrelated event types;
- return non-2xx on processing failure so Stripe retries delivery;
- use bounded SDK network retries together with mutation-specific idempotency keys.

### 2.4 Stripe CLI testing

Repository: `stripe/stripe-cli`

- Listen/forward workflow:  
  https://github.com/stripe/stripe-cli/wiki/listen-command
- Trigger test events:  
  https://github.com/stripe/stripe-cli/wiki/trigger-command

These commands validate signature delivery and retry behavior. A real SportReel test-mode PaymentSheet purchase is still required for metadata, price, database and fulfillment evidence because a generic generated event does not contain a real SportReel payment row.

### 2.5 Receipt ownership

Official Stripe documentation:  
https://docs.stripe.com/payments/advanced/receipts

Stripe documents that a PaymentIntent created with `receipt_email` sends a receipt after a successful payment. SportReel therefore uses `receipt_email` as the **single receipt path**. The webhook does not send a second custom payment-confirmation email.

## 3. Critical findings and resolutions

### Finding A — price units were inconsistent

The `pricing.price_ils` seed stores human-readable values such as `79`, but Stripe requires ILS in agorot. The old server sent `79` directly to Stripe while the mobile UI divided it by 100, risking a charge of ₪0.79 instead of ₪79.

Resolution:

- `pricing.price_ils` remains human-readable major ILS units;
- operator API and UI read/write the same major-unit value;
- `ilsToMinorUnits` converts exactly once with `Math.round(value * 100)` at each Stripe boundary;
- `payments.amount_ils` and `purchases.amount_ils` record the Stripe minor-unit amount for reconciliation;
- analytics revenue converts the confirmed Stripe amount back to major ILS.

### Finding B — download tokens could be null

The original database schema declared `download_token` without a default, while the checkout API did not always generate one. A successful payment could therefore reach the app without a usable purchase credential.

Resolution:

- the server explicitly generates a UUID token;
- fresh schema and migration add a UUID default, backfill existing nulls, and enforce `NOT NULL`;
- mobile awaits SecureStore persistence before presenting PaymentSheet;
- the download endpoint still refuses access until webhook-backed status is `completed`.

### Finding C — duplicate PaymentIntents were possible

Repeated taps, transport retries, process restarts, or an ambiguous mobile response could create multiple PaymentIntents for the same purchase attempt.

Resolution:

- mobile persists one checkout-attempt ID in SecureStore;
- the server uses it as the Stripe request `idempotencyKey`;
- the unique `stripe_payment_intent_id` row is reused on replay;
- terminal success/failure clears that checkout-attempt ID;
- stripe-node has bounded network retries, while request-level idempotency remains mandatory.

### Finding D — the app claimed success before durable fulfillment

The old success screen displayed “Payment confirmed” immediately after PaymentSheet returned without error. That proves client confirmation completed, but it is not durable server fulfillment.

Resolution:

- the mobile app first displays “Finalizing payment”;
- it polls a bearer-token-scoped payment-status endpoint;
- only `payments.status='completed'`, written by the signed webhook, displays “Payment confirmed” and enables download;
- failed/canceled payments remain locked and rotate the next checkout-attempt ID.

### Finding E — webhook replay and duplicate email risk

The previous webhook updated state and inserted analytics without amount/currency/ownership reconciliation. Re-delivery could duplicate analytics. During self-review, a second problem was found: `receipt_email` already asked Stripe to send a compliant receipt, while the webhook also sent a custom payment confirmation, which could produce two customer emails.

Resolution:

- verify PaymentIntent currency, minor-unit amount, `reel_id`, and durable payment row before fulfillment;
- handle `payment_intent.succeeded`, `payment_intent.payment_failed`, and `payment_intent.canceled`;
- never regress a completed payment to failed;
- enforce one `(payment_id, event_type)` analytics row;
- retain `receipt_email` on PaymentIntent creation and let Stripe own the single receipt;
- remove custom receipt sending and unused receipt-claim database columns from the webhook/schema;
- return HTTP 500 for retriable database processing failure.

### Finding F — in-memory token storage lost purchases after restart

The previous Zustand-only token disappeared after process death or redirect recovery.

Resolution:

- store the bearer token in Expo SecureStore;
- hydrate it when the success screen reopens;
- keep it out of routes, screenshots, logs and navigation history;
- delete it after successful download.

## 4. Digital-product store policy blocker

The official `stripe/stripe-react-native` README states that digital products or services unlocked inside an App Store or Google Play app must use the store's in-app purchase APIs. SportReel currently sells a downloadable digital video.

Therefore this technical Stripe implementation is **blocked from being treated as an App Store / Google Play production payment solution** until one of these paths is formally chosen and verified:

1. Apple/Google in-app purchase for the consumer digital video;
2. purchase on the web, with the app acting only as a signed-in viewer/downloader of an externally purchased item;
3. a documented store-policy exception applicable to the exact SportReel product and distribution model;
4. private/enterprise/direct distribution where consumer-store billing rules do not apply.

Current safeguard:

- internal `development` and `preview` builds may use Stripe test mode;
- the `production` EAS store profile sets `EXPO_PUBLIC_STRIPE_IN_APP_ENABLED=false`;
- Apple Pay or Google Pay are not enabled as a workaround, because wallets inside PaymentSheet do not replace store billing requirements for a digital product.

## 5. Implementation checklist

### Server

- [x] Calculate price from the server-side reel/sport pricing table.
- [x] Convert major ILS to minor units exactly once at Stripe boundaries.
- [x] Create PaymentIntent with `automatic_payment_methods`.
- [x] Attach payer email through `receipt_email` and SportReel metadata.
- [x] Use a persisted Stripe idempotency key.
- [x] Persist a non-null UUID download token.
- [x] Return no secret key or raw payment-method data to mobile.
- [x] Enable bounded stripe-node transport retries.

### React Native

- [x] Configure one root `StripeProvider`.
- [x] Install Stripe's Expo config plugin.
- [x] Configure the `sportreel` redirect scheme.
- [x] Forward cold-start and live redirect URLs to `handleURLCallback`.
- [x] Call `initPaymentSheet` before `presentPaymentSheet`.
- [x] Handle canceled, failed and timed-out PaymentSheet results.
- [x] Persist the bearer token and checkout-attempt ID in SecureStore.
- [x] Avoid putting payment capabilities in navigation URLs.
- [x] Wait for webhook-backed status before success/download.
- [x] Disable Stripe digital-content checkout in the store-production profile.

### Webhook and fulfillment

- [x] Verify the raw-body Stripe signature.
- [x] Validate currency, amount, reel ownership and payment-row identity.
- [x] Complete payment/reel state only for a valid succeeded intent.
- [x] Persist failed/canceled terminal state without regressing completed state.
- [x] Deduplicate analytics events.
- [x] Use Stripe's `receipt_email` as the single receipt path.
- [x] Remove duplicate custom payment-confirmation email delivery.
- [x] Return 500 for retriable processing failure.
- [x] Keep download locked until durable completed state.

### Tests and deployment

- [x] Add `scripts/test_stripe_official_payment_contract.py`.
- [x] Add `.github/workflows/stripe-official-payment-contract.yml` with contract, web type-check and mobile type-check.
- [ ] Pass all workflows on the final PR head.
- [ ] Review and apply `20260721_harden_payment_download_tokens.sql`.
- [ ] Verify token default/not-null and analytics uniqueness in live Supabase.
- [ ] Deploy the Web API to Vercel.
- [ ] Publish the correct mobile update/build through EAS.
- [ ] Execute a Stripe test-mode PaymentSheet purchase in an internal build.
- [ ] Confirm one PaymentIntent and one payment row after repeated taps/retries.
- [ ] Confirm webhook signature rejection for an invalid payload.
- [ ] Confirm succeeded webhook unlocks exactly one purchase and analytics row.
- [ ] Confirm failed/canceled payment remains locked and can start a fresh attempt.
- [ ] Confirm app restart preserves the secure token and resumes status polling.
- [ ] Confirm Stripe sends one receipt to the payer email and SportReel sends no duplicate.
- [ ] Confirm download URL expires after 15 minutes.
- [ ] Resolve App Store / Google Play digital-product billing before consumer release.

## 6. Closure rule

This audit is not closed by type-checks or static contracts alone. Closure requires:

- final-head CI green;
- migration applied and live-verified;
- Vercel/EAS deployment verified;
- one real Stripe test-mode purchase through an internal app build;
- webhook, database, Stripe receipt, analytics, restart recovery and download evidence;
- a documented distribution/payment-policy decision for the digital video product.
