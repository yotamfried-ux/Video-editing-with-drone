from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def require(text: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing required Stripe contract tokens: {missing}")


checkout_route = read("web-api/src/app/api/checkout/stripe/route.ts")
pricing = read("web-api/src/lib/pricing.ts")
stripe_client = read("web-api/src/lib/stripe.ts")
webhook = read("web-api/src/app/api/webhooks/stripe/route.ts")
status_route = read("web-api/src/app/api/payment-status/[download_token]/route.ts")
download_route = read("web-api/src/app/api/download/[download_token]/route.ts")
checkout_screen = read("mobile/src/app/checkout/[reel_id].tsx")
success_screen = read("mobile/src/app/success/[reel_id].tsx")
checkout_hook = read("mobile/src/features/payment/hooks/useCheckout.ts")
token_store = read("mobile/src/features/payment/downloadTokenStore.ts")
root_layout = read("mobile/src/app/_layout.tsx")
core_schema = read("supabase/migrations/20260612_create_core_schema.sql")
hardening_migration = read("supabase/migrations/20260721_harden_payment_download_tokens.sql")
audit = read("docs/audit/stripe-mobile-payment-official-reference-audit-20260721.md")

require(
    checkout_route,
    [
        "automatic_payment_methods: { enabled: true }",
        "receipt_email: email",
        "metadata:",
        "reel_id: reelId",
        "checkout_session_id: checkoutSessionId",
        "{ idempotencyKey }",
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
        "receipt_email_claimed_at",
        "return NextResponse.json({ received: true })",
    ],
    "signed webhook fulfillment",
)
if webhook.index("const rawBody = await req.text()") > webhook.index("stripe.webhooks.constructEvent"):
    raise SystemExit("webhook signature verification must consume the raw body before parsing")

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
        "checkout_session_id: checkoutSessionId.current",
        "newCheckoutSessionId(reelId)",
        "payerEmail",
    ],
    "mobile idempotency key",
)
require(
    checkout_screen,
    [
        "initPaymentSheet",
        "presentPaymentSheet",
        "paymentIntentClientSecret: checkout.clientSecret",
        "returnURL: 'sportreel://stripe-redirect'",
        "PaymentSheetError.Canceled",
        "await setDownloadToken",
        "router.replace(`/success/${reel_id}`)",
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
    ],
    "secure bearer-token storage",
)
require(root_layout, ["<StripeProvider", 'urlScheme="sportreel"'], "StripeProvider root config")

require(
    core_schema + hardening_migration,
    [
        "download_token",
        "default gen_random_uuid()::text",
        "receipt_email_sent_at",
        "receipt_email_claimed_at",
        "analytics_payment_event_uidx",
    ],
    "Stripe persistence schema",
)
if "('surfing',        79)" not in core_schema:
    raise SystemExit("fixture expects major-unit pricing seed to remain human-readable")

require(
    audit,
    [
        "stripe/stripe-react-native",
        "stripe-samples/accept-a-payment",
        "stripe/stripe-node",
        "digital product",
        "App Store",
        "Google Play",
        "blocked",
    ],
    "official Stripe reference audit",
)

print("Official Stripe mobile payment contract checks passed")
