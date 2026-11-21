import { recoveryParams } from './recoveryLink';

describe('SportReel password recovery deep links', () => {
  it('accepts only the app recovery route', () => {
    expect(recoveryParams('https://attacker.example/reset-password#access_token=bad')).toBeNull();
    expect(recoveryParams('sportreel://checkout#access_token=bad')).toBeNull();
    expect(recoveryParams('sportreel://reset-password#access_token=ok&refresh_token=refresh&type=recovery')?.get('access_token')).toBe('ok');
  });

  it('supports both Supabase implicit fragments and PKCE codes', () => {
    expect(recoveryParams('sportreel://reset-password#access_token=a&refresh_token=b&type=recovery')?.get('type')).toBe('recovery');
    expect(recoveryParams('sportreel://reset-password?code=code123')?.get('code')).toBe('code123');
    expect(recoveryParams('sportreel:///reset-password?code=x')?.get('code')).toBe('x');
  });

  it('rejects malformed URLs', () => {
    expect(recoveryParams('not a url')).toBeNull();
    expect(recoveryParams('')).toBeNull();
  });
});
