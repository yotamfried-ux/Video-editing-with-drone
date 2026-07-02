# Operator API boundary

Operator-only mobile screens must use the operator API boundary for privileged data.

## Rule

Operator screens should call `operatorFetch()` for operator-only state instead of reading Supabase tables directly from the mobile app.

## Why

The operator API attaches the operator secret and lets the server use privileged Supabase access safely. Direct mobile reads can bypass the debugging and authorization boundary that the operator app relies on.

## Current status reads

- Global live pipeline status: `GET /api/operator/pipeline/status`
- Pipeline run history: `GET /api/operator/pipeline/runs`
- Delivery run history: `GET /api/operator/delivery-status`

## Allowed direct mobile Supabase access

Direct Supabase access is still allowed for end-user auth, user profile, athlete photo upload, and RLS-protected athlete data.

## Not allowed

Do not import `@/shared/lib/supabase` from operator-only mobile screens or operator feature code for privileged state. Add or use an operator API route instead.
