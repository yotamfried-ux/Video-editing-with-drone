# App store readiness and the payment provider plugin

Scope: the Expo app in `mobile/` and the routes it calls in `web-api/`. Checked on this branch; items marked
**operator** cannot be done from the repository.

## 1. Payment provider plugin

One user-facing payment mechanism: the server creates a hosted payment page and the app opens it. Which payment
company hosts the page is a server-side plugin.

```
mobile  POST /api/checkout/:token ──► activeProvider().createCheckout()  ──► hosted payment page (browser)
provider ──► POST /api/payments/webhook/<provider> ──► provider.parseWebhook() ──► applyPaymentEvent()
web     GET  /api/checkout/session?provider=…&session_id=… ──► provider.getSessionStatus() + purchase row
```

| piece | file |
|---|---|
| contract (`PaymentProvider`) | `web-api/src/lib/payments/types.ts` |
| selection (`PAYMENT_PROVIDER`, default `stripe`, fails closed) | `web-api/src/lib/payments/registry.ts` |
| Stripe plugin | `web-api/src/lib/payments/providers/stripe.ts` |
| Grow placeholder (registered, `isConfigured() === false`) | `web-api/src/lib/payments/providers/grow.ts` |
| provider-independent paid/expired transitions | `web-api/src/lib/payments/fulfillment.ts` |
| app client (names no provider) | `mobile/src/features/payment/` |

Adding Grow: implement the three methods in `providers/grow.ts` from the merchant's Grow API documentation and
sandbox credentials, make `isConfigured()` check its secrets, point Grow's notification URL at
`/api/payments/webhook/grow`, set `PAYMENT_PROVIDER=grow`. No route, database or app change, and no app release.
The Grow request fields and notification authentication are deliberately not guessed here.

`purchases.stripe_checkout_session_id` and `stripe_payment_intent_id` keep their names and hold the active
provider's session id and payment reference; `metadata.provider` records which provider. A rename needs a migration.

Tests: `web-api/scripts/payments-plugin.test.ts` (provider selection fails closed, signed/unsigned/unsettled Stripe
events, idempotent fulfilment), and the PAY-02 and single-mechanism workflows, updated to the plugin layout.

## 2. Bugs fixed

| bug | fix |
|---|---|
| Two dynamic routes at the same path, `checkout/[reel_id].tsx` and `checkout/[token].tsx` | one screen, `checkout/[token].tsx` |
| `/success/:id` showed "You own it! Payment confirmed" to anyone opening the link; nothing navigated to it and its download token was never set (it also called a download route backed by the retired `payments` table) | screen and token store removed; the web success page is the delivery path and now links back to the app |
| Stripe native SDK (`@stripe/stripe-react-native`, `StripeProvider`) shipped in the binary but never used; the production EAS profile carried a Stripe **test** key | dependency, provider and env var removed |
| Discover showed "No sessions yet" when the request failed, and `onEndReached` started overlapping page loads | error state with retry; one request at a time |
| Reel screen stayed on "Loading…" forever when opened without a token | shows "Clip unavailable" |
| A checkout whose payment page could not be created left a `checkout_created` purchase row | row is closed as `failed`; the app sees a clean error |
| Prices with agorot were rounded (`₪49.90` shown as `₪50`) | exact amount |

## 3. Store requirements added

| requirement | where |
|---|---|
| In-app account deletion (App Store 5.1.1(v), Google Play) | Profile → Delete Account → `DELETE /api/account` (caller's own token; cascades profile and push tokens) |
| Terms and Privacy Policy readable in the app and accepted at sign-up | `/legal/terms`, `/legal/privacy`, links on Register and Profile |
| Public policy URLs for the listings | `<web-api>/legal/privacy`, `<web-api>/legal/terms` (generated from the app's text; `scripts/sync_legal_text.py --check`) |
| iOS export compliance | `ITSAppUsesNonExemptEncryption: false` (HTTPS only) |

## 4. Verified

- `mobile`: `tsc --noEmit`, jest (6 suites), `expo export` for Android and iOS (both Hermes bundles build).
- `web-api`: `tsc --noEmit`, `next build`, plugin tests, operator auth boundary (34 handlers), and HTTP against the
  built server: `DELETE /api/account` without a token → 401; unsigned/wrongly signed Stripe webhook → 400;
  `/api/payments/webhook/grow` and unknown providers → 400; `/legal/*` → 200.

Not verified here: a device build (EAS), a real payment end to end, a real account deletion against production, and
`expo-doctor`'s online checks (Expo API unreachable from this host; its one offline finding is `expo-modules-core`
as a direct dependency, which the local `sportreel-source-reader` module uses).

## 5. Open before submission (**operator**)

1. **Store payment policy.** The reel is paid for on an external payment page. Apple (3.1.1) and Google Play require
   their own in-app purchase for digital content used in the app; goods and services consumed outside the app are
   exempt (3.1.3(e)). Whether a filmed-session reel counts as one or the other is a review risk that code cannot
   settle. Decide before submission; an IAP provider would be another plugin on the same contract.
2. **Hidden operator entry.** Five taps on the Profile logo open the operator console (biometric-gated). Reviewers
   must be told about it and given a demo account in the review notes (App Store 2.3.1).
3. `eas.json` → `submit.production.ios`: `appleId` and `ascAppId` are `FILL_IN`; Android needs
   `google-service-account.json`.
4. Stripe: the server must hold live keys before real customers pay (the app no longer holds any Stripe key).
5. Store listing: screenshots, description, age rating, data-safety / privacy nutrition labels (email, name, push
   token, purchase records, usage events — see the privacy policy), support URL.
6. No password reset flow exists in the app. Not a store requirement; worth adding before public launch.
7. The legal texts were not reviewed for legal adequacy in this change; only the account-deletion sentence was added.
