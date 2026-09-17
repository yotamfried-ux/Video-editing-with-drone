import { createClient } from '@supabase/supabase-js';
import { secureStorage } from './secureStorage';
import { SUPABASE_URL, SUPABASE_ANON_KEY } from './publicEnv';

// `publicEnv` already falls back to the committed non-secret defaults, so this
// only fires when someone explicitly points the app at a blank/invalid value
// (e.g. `EXPO_PUBLIC_SUPABASE_URL=` in mobile/.env). Fail with a message that
// names the fix instead of supabase-js's bare `supabaseUrl is required.`
function assertConfigured(): void {
  const missing: string[] = [];
  if (!SUPABASE_URL) missing.push('EXPO_PUBLIC_SUPABASE_URL');
  if (!SUPABASE_ANON_KEY) missing.push('EXPO_PUBLIC_SUPABASE_ANON_KEY');
  if (missing.length > 0) {
    throw new Error(
      `Supabase is not configured: ${missing.join(', ')} resolved to an empty ` +
        `value. Copy mobile/.env.example to mobile/.env and fill it in, or ` +
        `remove the blank override so the committed default applies.`
    );
  }
  if (!/^https?:\/\//.test(SUPABASE_URL)) {
    throw new Error(
      `Supabase is not configured: EXPO_PUBLIC_SUPABASE_URL must start with ` +
        `http:// or https:// (got "${SUPABASE_URL}"). Check mobile/.env.`
    );
  }
}

assertConfigured();

export const supabase = createClient(
  SUPABASE_URL,
  SUPABASE_ANON_KEY,
  {
    auth: {
      // Encrypted keychain storage (not plaintext AsyncStorage) for the
      // session + refresh token.
      storage: secureStorage,
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: false,
    },
  }
);
