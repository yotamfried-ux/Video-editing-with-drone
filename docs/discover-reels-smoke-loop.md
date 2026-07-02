# Discover reels smoke loop

This loop verifies the Discover → Checkout path without mixing it with the operator app-pipeline dispatch loop.

## Scope

This covers:

- Discover session visibility through `GET /api/sessions`.
- Checkout creation through `POST /api/checkout/[token]`.
- Operator-only diagnostics through `GET /api/operator/discover-diagnostics`.
- Database-level expiry behavior for `public.reels.expires_at`.

This does not cover:

- Running the full video pipeline.
- Delivery approval from Review.
- Stripe webhook completion and sold-state verification. Those belong to the broader end-to-end validation loop.

## Safety invariants

- Public Discover and checkout routes are not made privileged routes.
- Operator diagnostics stay behind `requireOperator(req)` and rate limiting.
- The expiry migration does not touch sold, expired, or already-expiring reels.
- Diagnostic SQL must not delete production rows.

## Migration verification

Run `supabase/diagnostics/reel_expiry_default_check.sql` after applying migrations.

Expected result: `public.reels.expires_at` has a default equivalent to `now() + interval '7 days'`.

Run `supabase/diagnostics/backfill_reel_expiry.sql` before applying the migration if you need to preview active rows that will be repaired.

## Smoke procedure

1. Apply migrations.
2. Run `supabase/diagnostics/discover_smoke_test.sql` in Supabase SQL Editor.
3. Copy the returned `token`.
4. Call `GET /api/sessions?sport=stripe_test` and confirm the smoke reel appears.
5. Call `GET /api/operator/discover-diagnostics` with `x-operator-secret` and confirm:
   - `ok: true`
   - `missingExpiryCount: 0` for active rows after migration/backfill
   - the smoke reel is visible under `reels` and grouped under `sessions`
6. Call `POST /api/checkout/{token}` and confirm a checkout URL is returned.
7. Complete Stripe Sandbox checkout only when testing payment completion. Record webhook and sold-state results in the broader end-to-end validation notes.

## Rollback notes

If the expiry default causes an unexpected operational issue, remove only the default:

```sql
alter table public.reels
  alter column expires_at drop default;
```

Do not bulk-clear `expires_at`; the migration intentionally leaves existing row values intact after repair.
