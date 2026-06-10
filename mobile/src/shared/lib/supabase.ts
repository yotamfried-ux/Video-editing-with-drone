import { createClient } from '@supabase/supabase-js';
import { secureStorage } from './secureStorage';

export const supabase = createClient(
  process.env.EXPO_PUBLIC_SUPABASE_URL!,
  process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY!,
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
