import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform } from 'react-native';
import { accessToken, authedFetch } from '@/shared/lib/authedFetch';
import { useAuthStore } from '@/shared/hooks/useAuth';

export interface ReelOwnership {
  purchased: boolean;
  download_url: string | null;
  can_follow: boolean;
  following: boolean;
}

export type OwnershipStatus =
  | 'unknown_loading'
  | 'unauthenticated'
  | 'not_owned'
  | 'owned'
  | 'network_error';

/**
 * APP-004: Explicit ownership state machine so transient network errors never disguise an owned
 * reel as "not purchased" (preventing duplicate purchase attempts) and auth changes re-verify.
 */
export function useReelOwnership(token: string | undefined) {
  const userId = useAuthStore((s) => s.user?.id ?? null);
  const [ownership, setOwnership] = useState<ReelOwnership | null>(null);
  const [status, setStatus] = useState<OwnershipStatus>('unknown_loading');
  const [ownershipError, setOwnershipError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqCounter = useRef(0);

  const refresh = useCallback(async () => {
    const reqId = ++reqCounter.current;
    if (!token) {
      setOwnership(null);
      setStatus('unauthenticated');
      setOwnershipError(null);
      return;
    }
    const jwt = await accessToken();
    if (reqId !== reqCounter.current) return;
    if (!jwt) {
      setOwnership(null);
      setStatus('unauthenticated');
      setOwnershipError(null);
      return;
    }
    setStatus((prev) => (prev === 'owned' ? 'owned' : 'unknown_loading'));
    setOwnershipError(null);
    try {
      const next = await authedFetch<ReelOwnership>(`/api/reels/${encodeURIComponent(token)}/ownership`);
      if (reqId !== reqCounter.current) return;
      setOwnership(next);
      setStatus(next.purchased ? 'owned' : 'not_owned');
    } catch (e) {
      if (reqId !== reqCounter.current) return;
      setOwnershipError(e instanceof Error ? e.message : 'Could not verify purchase status');
      // Keep prior verified ownership if already loaded; otherwise surface network_error explicitly.
      setStatus((prev) => (prev === 'owned' ? 'owned' : 'network_error'));
    }
  }, [token, userId]);

  useEffect(() => {
    void refresh();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void refresh();
    });
    let cleanupWeb: (() => void) | undefined;
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      const onFocus = () => void refresh();
      window.addEventListener('focus', onFocus);
      window.addEventListener('pageshow', onFocus);
      cleanupWeb = () => {
        window.removeEventListener('focus', onFocus);
        window.removeEventListener('pageshow', onFocus);
      };
    }
    return () => {
      sub.remove();
      cleanupWeb?.();
    };
  }, [refresh]);

  const setFollowing = useCallback(
    async (follow: boolean) => {
      if (!token || busy) return;
      setBusy(true);
      setError(null);
      try {
        const result = await authedFetch<{ following: boolean }>(
          `/api/reels/${encodeURIComponent(token)}/follow`,
          { method: follow ? 'POST' : 'DELETE' },
        );
        setOwnership((prev) => (prev ? { ...prev, following: result.following } : prev));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not update');
      } finally {
        setBusy(false);
      }
    },
    [token, busy],
  );

  return { ownership, status, ownershipError, busy, error, refresh, setFollowing };
}
