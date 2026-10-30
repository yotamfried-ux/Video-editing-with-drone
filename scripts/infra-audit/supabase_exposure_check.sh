#!/usr/bin/env bash
# Read-only check of which schemas the Supabase REST API exposes. GET requests only; prints status codes and PostgREST error codes,
# never keys. Requires SUPABASE_URL and a public/anon key in SUPABASE_ANON_KEY (service key NOT needed and not used).
#   SUPABASE_URL=https://<ref>.supabase.co SUPABASE_ANON_KEY=... ./supabase_exposure_check.sh [schema]
set -u
: "${SUPABASE_URL:?set SUPABASE_URL}"; : "${SUPABASE_ANON_KEY:?set SUPABASE_ANON_KEY}"
schema="${1:-ground_truth}"
probe() {  # $1 = schema profile
  curl -sS -o /tmp/.sx_body -w '%{http_code}' -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
       -H "Accept-Profile: $1" "$SUPABASE_URL/rest/v1/" 2>/dev/null
}
echo "1) exposed-schema list (a bogus profile makes PostgREST name the allowed ones):"
code=$(probe "__definitely_not_a_schema__"); echo "   HTTP $code"; grep -o '"message":"[^"]*"' /tmp/.sx_body | head -1
echo "2) is '$schema' reachable through the API?"
code=$(probe "$schema"); echo "   HTTP $code"; grep -o '"code":"[^"]*"' /tmp/.sx_body | head -1
if [ "$code" = "200" ]; then echo "   !! '$schema' IS EXPOSED through the REST API — remove it from Settings > API > Exposed schemas"; exit 1; fi
echo "   OK: not exposed (406/PGRST106 means 'invalid schema')"
rm -f /tmp/.sx_body
