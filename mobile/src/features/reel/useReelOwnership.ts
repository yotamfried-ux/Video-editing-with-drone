import { useCallback, useEffect, useState } from 'react';
import { AppState } from 'react-native';
import { accessToken, authedFetch } from '@/shared/lib/authedFetch';

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!token || !(await accessToken())) {
      setOwnership(null);
      return;
    }
    try {
      setOwnership(await authedFetch<ReelOwnership>(`/api/reels/${encodeURIComponent(token)}/ownership`));
    } catch {
      setOwnership(null); // unknown is shown as "not purchased": the buy button stays
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

  return { ownership, busy, error, refresh, setFollowing };
}
