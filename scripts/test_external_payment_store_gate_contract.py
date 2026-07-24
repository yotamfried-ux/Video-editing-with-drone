from pathlib import Path

checkout = Path('mobile/src/app/checkout/[reel_id].tsx').read_text(encoding='utf-8')
eas = Path('mobile/eas.json').read_text(encoding='utf-8')

required_checkout = [
    "process.env.EXPO_PUBLIC_STRIPE_IN_APP_ENABLED === 'true'",
    "const bitEnabled = externalDigitalPaymentsEnabled && process.env.EXPO_PUBLIC_BIT_ENABLED === 'true'",
    'disabled={busy || !externalDigitalPaymentsEnabled}',
    '{bitEnabled && (',
    'External payment providers are disabled in consumer store builds',
]
missing = [token for token in required_checkout if token not in checkout]
if missing:
    raise SystemExit(f'external payment store gate missing: {missing}')

for forbidden in [
    "EXPO_PUBLIC_STRIPE_IN_APP_ENABLED !== 'false'",
    '!!process.env.EXPO_PUBLIC_BIT_ENABLED',
]:
    if forbidden in checkout:
        raise SystemExit(f'external payment store gate is fail-open: {forbidden}')

if '"production"' not in eas or '"EXPO_PUBLIC_STRIPE_IN_APP_ENABLED": "false"' not in eas:
    raise SystemExit('production EAS profile must explicitly disable external digital payments')

print('External digital payment store gate checks passed')
