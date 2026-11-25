function fromEnv(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

function defaultWebApiBaseUrl(): string {
  if (typeof window !== 'undefined' && window.location) {
    // Standalone Expo dev server typically runs on 8081/19006; co-hosted Next.js/Vercel serves /api/* same-origin.
    if (window.location.port !== '8081' && window.location.port !== '19006') {
      return '';
    }
  }
  return 'https://video-editing-with-drone.vercel.app';
}

export const SUPABASE_URL = fromEnv(
  process.env.EXPO_PUBLIC_SUPABASE_URL,
  'https://bcndgmymnismbxvdeetc.supabase.co'
);

export const SUPABASE_ANON_KEY = fromEnv(
  process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY,
  'sb_publishable_mwAM5lvgulv3sCtrHm-OkA_4wMCpNZJ'
);

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL?.trim()
  ? process.env.EXPO_PUBLIC_API_BASE_URL.trim()
  : defaultWebApiBaseUrl();

export const APP_DOMAIN = fromEnv(
  process.env.EXPO_PUBLIC_APP_DOMAIN,
  'sportreel.app'
);
