# GAP-005 — Operator status API boundary

Status: fixed on 2026-07-02.

## Problem

The operator Pipeline screen read the global `pipeline_status` row directly from the mobile app through the Supabase anon client.

That mixed operator-only operational state with end-user Supabase access and made debugging and authorization inconsistent.

## Fix

- Added `GET /api/operator/pipeline/status`.
- The route requires operator authorization.
- The route reads `pipeline_status` server-side.
- `usePipelineStatus` now calls the route with `operatorFetch()`.
- Direct Supabase reads are no longer used in `mobile/src/features/operator`.

## Classification

Allowed direct mobile Supabase access remains limited to end-user auth, user profile, athlete photo upload, and RLS-protected athlete data.

Operator-only state must go through operator API routes.

## Verification

- Searched for `pipeline_status` and direct Supabase access in operator mobile code.
- Confirmed `usePipelineStatus` was the operator status read that needed migration.
- Confirmed `operatorFetch()` attaches the operator secret for the new API route.
