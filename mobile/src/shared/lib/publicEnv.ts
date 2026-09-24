/**
 * Public (non-secret) client configuration.
 *
 * Every value here is safe to ship in the app bundle: the Supabase
 * publishable key and the Stripe publishable key are designed to be public,
 * and access is enforced server-side by RLS and the web-api boundary.
 *
 * Resolution order for each value:
 *   1. `process.env.EXPO_PUBLIC_*` — set by `mobile/.env` for local runs and
 *      by the `env` block of the matching `eas.json` build profile for builds.
 *   2. The committed default below, which mirrors `eas.json`.
 *
 * The defaults exist so a fresh clone runs with `npx expo start` and no
 * setup. `mobile/.env` is gitignored, so without them the Supabase client
 * was constructed with an empty URL and threw `supabaseUrl is required.` at
 * import time, taking the whole app down before the login screen rendered.
 *
 * Copy `mobile/.env.example` to `mobile/.env` to point a local run at a
 * different project (a staging ref, a local `supabase start` stack, …).
 */

function fromEnv(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

export const SUPABASE_URL = fromEnv(
  process.env.EXPO_PUBLIC_SUPABASE_URL,
  'https://bcndgmymnismbxvdeetc.supabase.co'
);

export const SUPABASE_ANON_KEY = fromEnv(
  process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY,
  'sb_publishable_mwAM5lvgulv3sCtrHm-OkA_4wMCpNZJ'
);

export const API_BASE_URL = fromEnv(
  process.env.EXPO_PUBLIC_API_BASE_URL,
  'https://video-editing-with-drone.vercel.app'
);

export const APP_DOMAIN = fromEnv(
  process.env.EXPO_PUBLIC_APP_DOMAIN,
  'sportreel.app'
);
