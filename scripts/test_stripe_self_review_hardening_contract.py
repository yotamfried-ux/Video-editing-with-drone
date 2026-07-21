from pathlib import Path

checkout = Path('web-api/src/app/api/checkout/stripe/route.ts').read_text(encoding='utf-8')
migration = Path('supabase/migrations/20260721_harden_payment_download_tokens.sql').read_text(encoding='utf-8')

required_checkout = [
    "select('status, expires_at, storage_path')",
    "reel.status === 'sold'",
    "reel.status === 'expired'",
    "PURCHASABLE_STATUSES.has(reel.status)",
    "!reel.storage_path",
    "This reel was already sold",
    "This reel has expired",
]
missing = [token for token in required_checkout if token not in checkout]
if missing:
    raise SystemExit(f'PaymentIntent sellability guard missing: {missing}')

availability_index = checkout.index("select('status, expires_at, storage_path')")
intent_index = checkout.index('stripe.paymentIntents.create')
if availability_index > intent_index:
    raise SystemExit('reel availability must be verified before creating a PaymentIntent')

required_migration = [
    'with ranked_payment_events as (',
    'partition by payment_id, event_type',
    'ranked.duplicate_rank > 1',
    'create unique index if not exists analytics_payment_event_uidx',
]
missing = [token for token in required_migration if token not in migration]
if missing:
    raise SystemExit(f'live-safe analytics dedup migration missing: {missing}')

if migration.index('ranked.duplicate_rank > 1') > migration.index('create unique index if not exists analytics_payment_event_uidx'):
    raise SystemExit('existing analytics duplicates must be removed before the unique index is created')

print('Stripe fallback self-review hardening checks passed')
