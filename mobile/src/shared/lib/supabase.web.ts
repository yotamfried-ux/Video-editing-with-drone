import { createClient } from '@supabase/supabase-js';
import { secureStorage } from './secureStorage';
import { SUPABASE_URL, SUPABASE_ANON_KEY } from './publicEnv';

function assertConfigured(): void {
  const missing: string[] = [];
  if (!SUPABASE_URL) missing.push('EXPO_PUBLIC_SUPABASE_URL');
  if (!SUPABASE_ANON_KEY) missing.push('EXPO_PUBLIC_SUPABASE_ANON_KEY');
  if (missing.length > 0) {
    throw new Error(
      `Supabase is not configured: ${missing.join(', ')} resolved to an empty value.`
    );
  }
  if (!/^https?:\/\//.test(SUPABASE_URL)) {
    throw new Error(
      `Supabase is not configured: EXPO_PUBLIC_SUPABASE_URL must start with http:// or https:// (got "${SUPABASE_URL}").`
    );
  }
}

assertConfigured();

export const supabase = createClient(
  SUPABASE_URL,
  SUPABASE_ANON_KEY,
  {
    auth: {
      storage: secureStorage,
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: true,
    },
  }
);
