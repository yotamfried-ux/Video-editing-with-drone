/**
 * Regression: a fresh clone has no mobile/.env (it is gitignored and there was
 * no .env.example). That left EXPO_PUBLIC_SUPABASE_URL undefined, so
 * shared/lib/supabase.ts called createClient('', '') and supabase-js threw
 * `supabaseUrl is required.` at import time — the app died before the login
 * screen rendered and no account could sign in.
 */

const ENV_KEYS = [
  'EXPO_PUBLIC_SUPABASE_URL',
  'EXPO_PUBLIC_SUPABASE_ANON_KEY',
  'EXPO_PUBLIC_API_BASE_URL',
  'EXPO_PUBLIC_APP_DOMAIN',
] as const;

function loadPublicEnv(overrides: Partial<Record<string, string>>) {
  let mod: typeof import('./publicEnv');
  jest.isolateModules(() => {
    for (const key of ENV_KEYS) delete process.env[key];
    for (const [key, value] of Object.entries(overrides)) {
      if (value !== undefined) process.env[key] = value;
    }
    mod = require('./publicEnv');
  });
  return mod!;
}

describe('public client configuration', () => {
  const saved = { ...process.env };
  afterEach(() => {
    process.env = { ...saved };
  });

  it('resolves a usable Supabase config with no .env present', () => {
    const env = loadPublicEnv({});

    expect(env.SUPABASE_URL).toMatch(/^https:\/\/[a-z0-9]+\.supabase\.co$/);
    expect(env.SUPABASE_ANON_KEY).not.toBe('');
    expect(env.API_BASE_URL).toMatch(/^https:\/\//);
    expect(env.APP_DOMAIN).not.toBe('');
  });

  it('lets mobile/.env override every default', () => {
    const env = loadPublicEnv({
      EXPO_PUBLIC_SUPABASE_URL: 'https://staging.supabase.co',
      EXPO_PUBLIC_SUPABASE_ANON_KEY: 'sb_publishable_staging',
      EXPO_PUBLIC_API_BASE_URL: 'https://staging.example.com',
      EXPO_PUBLIC_APP_DOMAIN: 'staging.sportreel.app',
    });

    expect(env.SUPABASE_URL).toBe('https://staging.supabase.co');
    expect(env.SUPABASE_ANON_KEY).toBe('sb_publishable_staging');
    expect(env.API_BASE_URL).toBe('https://staging.example.com');
    expect(env.APP_DOMAIN).toBe('staging.sportreel.app');
  });

  it('treats a blank or whitespace-only override as unset', () => {
    const env = loadPublicEnv({
      EXPO_PUBLIC_SUPABASE_URL: '',
      EXPO_PUBLIC_SUPABASE_ANON_KEY: '   ',
    });

    expect(env.SUPABASE_URL).toMatch(/^https:\/\//);
    expect(env.SUPABASE_ANON_KEY).not.toBe('');
    expect(env.SUPABASE_ANON_KEY.trim()).toBe(env.SUPABASE_ANON_KEY);
  });

  it('keeps the committed defaults in sync with the eas.json build profiles', () => {
    const eas = require('../../../eas.json');
    const env = loadPublicEnv({});

    for (const profile of Object.values<any>(eas.build)) {
      if (!profile.env) continue;
      expect(profile.env.EXPO_PUBLIC_SUPABASE_URL).toBe(env.SUPABASE_URL);
      expect(profile.env.EXPO_PUBLIC_SUPABASE_ANON_KEY).toBe(env.SUPABASE_ANON_KEY);
      expect(profile.env.EXPO_PUBLIC_API_BASE_URL).toBe(env.API_BASE_URL);
    }
  });
});
