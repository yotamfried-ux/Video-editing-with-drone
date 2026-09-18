#!/usr/bin/env python3
"""Contract for centralized production API rate limiting."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rate = (ROOT / "web-api/src/lib/ratelimit.ts").read_text(encoding="utf-8")
migration = (ROOT / "supabase/migrations/20260918_supabase_rate_limit.sql").read_text(encoding="utf-8")
runner = (ROOT / "scripts/apply_upload_release_migrations.py").read_text(encoding="utf-8")
schema = (ROOT / "scripts/verify_upload_release_schema.sql").read_text(encoding="utf-8")

required_rate = [
    "import { supabaseAdmin } from '@/lib/supabase-admin';",
    "RATE_LIMIT_BACKEND ?? 'supabase'",
    "consume_api_rate_limit",
    "falling back to Supabase",
    "Rate limit service unavailable",
    "{ status: 503 }",
    "{ status: 429 }",
]
for token in required_rate:
    assert token in rate, f"ratelimit.ts missing {token!r}"

required_migration = [
    "create table if not exists public.api_rate_limit_windows",
    "create or replace function public.consume_api_rate_limit",
    "on conflict (limiter_key, window_start)",
    "hit_count = public.api_rate_limit_windows.hit_count + 1",
    "enable row level security",
    "revoke all on table public.api_rate_limit_windows from public, anon, authenticated",
    "grant execute on function public.consume_api_rate_limit",
]
for token in required_migration:
    assert token in migration, f"rate-limit migration missing {token!r}"

assert '"20260918_supabase_rate_limit.sql"' in runner
for token in [
    "table:api_rate_limit_windows",
    "rls:api_rate_limit_windows",
    "rpc:consume_api_rate_limit",
    "grant:api_rate_limit:no_client_rpc_execute",
    "grant:api_rate_limit:service_role_rpc_execute",
]:
    assert token in schema, f"schema verifier missing {token!r}"

print("PASS: production rate limiting defaults to Supabase and fails closed with explicit 503")
