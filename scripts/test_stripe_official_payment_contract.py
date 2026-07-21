import json
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def require(text: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing required Stripe contract tokens: {missing}")


checkout_route = read("web-api/src/app/api/checkout/stripe/route.ts")
web_checkout_route = read("web-api/src/app/api/checkout/[token]/route.ts")
pricing = read("web-api/src/lib/pricing.ts")
pricing_route = read("web-api/src/app/api/pricing/route.ts")
stripe_client = read("web-api/src/lib/stripe.ts")
webhook = read("web-api/src/app/api/webhooks/stripe/route.ts")
status_route = read("web-api/src/app/api/payment-status/[download_token]/route.ts")
download_route = read("web-api/src/app/api/download/[download_token]/route.ts")
checkout_screen = read("mobile/src/app/checkout/[reel_id].tsx")
success_screen = read("mobile/src/app/success/[reel_id].tsx")
checkout_hook = read("mobile/src/features/payment/hooks/useCheckout.ts")
token_store = read("mobile/src/features/payment/downloadTokenStore.ts")
root_layout = read("mobile/src/app/_layout.tsx")
app_json = json.loads(read("mobile/app.json"))
eas_json = json.loads(read("mobile/eas.json"))
operator_pricing = read("mobile/src/app/(operator)/pricing.tsx")
core_schema = read("supabase/migrations/20260612_create_core_schema.sql")
hardening_migration = read("supabase/migrations/20260721_harden_payment_download_tokens.sql")
audit = read("docs/audit/stripe-mobile-payment-official-reference-audit-20260721.md")

require(
    checkout_route,
    [
        "automatic_payment_methods: { enabled: true }",
        "receipt_email: email",
        "reel_id: reelId",
        "checkout_session_id: checkoutSessionId",
        "{ idempotencyKey }",
        "payment_intent_id: paymentIntentId",
        "Payment persistence returned no download token",
        "Stripe returned no PaymentIntent client secret",
    ],
    "PaymentIntent server route",
)
if "payload.amount" in checkout_route or "payload.price" in checkout_route:
    raise SystemExit("client-controlled amount must never reach PaymentIntent creation")

require(
    pricing,
    [
        "Math.round(majorUnits * 100)",
        "Configured reel price must be a positive ILS amount",
        "return ilsToMinorUnits(price.price_ils)",
    ],
    "server-side amount conversion",
)
require(
    web_checkout_route,
    [
        "import { ilsToMinorUnits } from '@/lib/pricing'",
        "unit_amount: amountMinor",
        "amount_ils: amountMinor",
        "amount_unit: 'agorot'",
    ],
    "Discover Checkout minor-unit conversion",
)
require(
    pricing_route,
    [
        "positive ILS amount",
        "Math.round(amount * 100) / 100",
    ],
    "operator pricing major-unit API",
)
if "priceIls / 100" in operator_pricing or "n * 100" in operator_pricing:
    raise SystemExit("operator pricing UI must edit human-readable major ILS values")

require(stripe_client, ["maxNetworkRetries: 2", "timeout: 20_000"], "stripe-node client")

require(
    webhook,
    [
        "const rawBody = await req.text()",
        "stripe.webhooks.constructEvent(rawBody, signature, webhookSecret)",
        "case 'payment_intent.succeeded'",
        "case 'payment_intent.payment_failed'",
        "case 'payment_intent.canceled'",
        "PaymentIntent reel_id does not match the payment row",
        "Unexpected PaymentIntent currency",
        "Payment amount mismatch",
        "onConflict: 'payment_id,event_type'",
        "Stripe owns the compliant",
        "return NextResponse.json({ received: true })",
    ],
    "signed webhook fulfillment",
)
if webhook.index("const rawBody = await req.text()") > webhook.index("stripe.webhooks.constructEvent"):
    raise SystemExit("webhook signature verification must consume the raw body before parsing")
if ".catch(() => {})" in webhook:
    raise SystemExit("webhook must await fulfillment side effects instead of fire-and-forget")
for duplicate_receipt_token in (
    "sendPaymentConfirmEmail",
    "receipt_email_sent_at",
    "receipt_email_claimed_at",
):
    if duplicate_receipt_token in webhook:
        raise SystemExit(f"webhook must not duplicate Stripe receipt delivery: {duplicate_receipt_token}")

require(
    status_route,
    [
        "eq('download_token', downloadToken)",
        "status === 'completed'",
        "ready: status === 'completed'",
    ],
    "webhook-backed payment status",
)
require(
    download_route,
    ["payment.status !== 'completed'", "createSignedUrl(storagePath, 900)"],
    "download authorization",
)

require(
    checkout_hook,
    [
        "getOrCreateCheckoutSessionId(reelId)",
        "checkout_session_id: checkoutSessionId",
        "payment_intent_id: string",
        "payerEmail",
    ],
    "mobile persisted idempotency key",
)
require(
    checkout_screen,
    [
        "initPaymentSheet",
        "presentPaymentSheet",
        "paymentIntentClientSecret: checkout.clientSecret",
        "returnURL: STRIPE_RETURN_URL",
        "defaultBillingDetails:",
        "PaymentSheetError.Canceled",
        "PaymentSheetError.Timeout",
        "await setDownloadToken",
        "router.replace(`/success/${reel_id}`)",
        "EXPO_PUBLIC_STRIPE_IN_APP_ENABLED",
    ],
    "React Native PaymentSheet",
)
if checkout_screen.index("initPaymentSheet") > checkout_screen.index("presentPaymentSheet"):
    raise SystemExit("PaymentSheet must be initialized before it is presented")

require(
    success_screen,
    [
        "/api/payment-status/",
        "fulfillment === 'completed'",
        "waiting for the signed server confirmation",
        "await clearToken(reel_id)",
        "await clearCheckoutSessionId(reel_id)",
    ],
    "webhook-owned mobile fulfillment",
)
if "Payment confirmed. Your clip is ready" in success_screen:
    raise SystemExit("mobile must not claim payment success before webhook confirmation")

require(
    token_store,
    [
        "expo-secure-store",
        "SecureStore.setItemAsync",
        "SecureStore.getItemAsync",
        "SecureStore.deleteItemAsync",
        "getOrCreateCheckoutSessionId",
        "clearCheckoutSessionId",
    ],
    "secure payment capability and idempotency storage",
)
require(
    root_layout,
    [
        "<StripeProvider",
        'urlScheme="sportreel"',
        "handleURLCallback",
        "Linking.getInitialURL()",
        "Linking.addEventListener('url'",
    ],
    "StripeProvider redirect handling",
)

plugins = app_json["expo"].get("plugins", [])
if not any(isinstance(plugin, list) and plugin[0] == "@stripe/stripe-react-native" for plugin in plugins):
    raise SystemExit("Expo app config must install Stripe's official config plugin")
if app_json["expo"].get("scheme") != "sportreel":
    raise SystemExit("Expo scheme must match the PaymentSheet return URL")

builds = eas_json.get("build", {})
if builds.get("production", {}).get("env", {}).get("EXPO_PUBLIC_STRIPE_IN_APP_ENABLED") != "false":
    raise SystemExit("consumer store build must keep Stripe digital-content checkout disabled")
for profile in ("development", "preview"):
    if builds.get(profile, {}).get("distribution") != "internal":
        raise SystemExit(f"Stripe test profile {profile} must remain internally distributed")

require(
    core_schema + hardening_migration,
    [
        "download_token",
        "default gen_random_uuid()::text",
        "analytics_payment_event_uidx",
    ],
    "Stripe persistence schema",
)
for dead_receipt_column in ("receipt_email_sent_at", "receipt_email_claimed_at"):
    if dead_receipt_column in core_schema + hardening_migration:
        raise SystemExit(f"schema must not retain unused custom-receipt state: {dead_receipt_column}")
if "('surfing',        79)" not in core_schema:
    raise SystemExit("pricing seed must remain human-readable major ILS")
if "amount_ils                numeric(10,2), -- Stripe minor units (agorot)" not in core_schema:
    raise SystemExit("payment amount unit must be explicit in the schema")

require(
    audit,
    [
        "stripe/stripe-react-native",
        "stripe-samples/accept-a-payment",
        "stripe/stripe-node",
        "PaymentSheet",
        "handleURLCallback",
        "receipt_email",
        "single receipt",
        "digital product",
        "App Store",
        "Google Play",
        "blocked",
    ],
    "official Stripe reference audit",
)

print("Official Stripe mobile payment contract checks passed")
