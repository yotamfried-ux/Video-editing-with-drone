import { createClient, SupabaseClient } from '@supabase/supabase-js';

// Lazy singleton: the client is created on first use, not at import time.
// This keeps `next build` from failing when env vars are absent at build,
// and avoids constructing a client in routes that never touch the DB.
let _client: SupabaseClient | null = null;

function client(): SupabaseClient {
  if (!_client) {
    _client = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_KEY!,
      { auth: { persistSession: false } }
    );
  }
  return _client;
}

export const supabaseAdmin = new Proxy({} as SupabaseClient, {
  get(_target, prop) {
    const c = client();
    const value = (c as unknown as Record<string | symbol, unknown>)[prop];
    return typeof value === 'function' ? value.bind(c) : value;
  },
});
