/**
 * Only accept recovery links routed to SportReel.
 * Do not log URLs: Supabase implicit-flow fragments contain sensitive tokens.
 */
export function recoveryParams(rawUrl: string): URLSearchParams | null {
  try {
    const url = new URL(rawUrl);
    const route = `${url.hostname}${url.pathname}`.replace(/^\/+|\/+$/g, '');
    if (url.protocol !== 'sportreel:' || route !== 'reset-password') return null;
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const query = url.searchParams;
    return fragment.has('access_token') || fragment.has('error')
      ? fragment
      : query;
  } catch {
    return null;
  }
}
