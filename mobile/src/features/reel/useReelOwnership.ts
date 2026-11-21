import { useCallback, useEffect, useState } from 'react';
import { AppState } from 'react-native';
import { accessToken, authedFetch } from '@/shared/lib/authedFetch';

export type OwnershipStatus = 'loading' | 'owned' | 'not_owned' | 'signed_out' | 'error';

export interface ReelOwnership {
  purchased: boolean;
  download_url: string | null;
  can_follow: boolean;
  following: boolean;
}

/**
 * Whether the signed-in user bought this reel and follows its athlete. Re-checked when the app returns to
 * the foreground, which is how the customer comes back from the payment page.
 */
export function useReelOwnership(token: string | undefined) {
  const [ownership, setOwnership] = useState<ReelOwnership | null>(null);
  const [status, setStatus] = useState<OwnershipStatus>('loading');
  const [ownershipError, setOwnershipError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus('loading');
    setOwnershipError(null);
    try {
      if (!token || !(await accessToken())) {
        setOwnership(null);
        setStatus('signed_out');
        return;
      }
      const result = await authedFetch<ReelOwnership>(`/api/reels/${encodeURIComponent(token)}/ownership`);
      setOwnership(result);
      setStatus(result.purchased ? 'owned' : 'not_owned');
    } catch {
      // Never turn an ownership lookup failure into "not purchased".
      // The user may already have paid: prevent a second purchase until resolved.
      setOwnership(null);
      setStatus('error');
      setOwnershipError('Could not verify your purchase. Check your connection and try again.');
    }
  }, [token]);

  useEffect(() => {
    refresh();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') refresh();
    });
    return () => sub.remove();
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
