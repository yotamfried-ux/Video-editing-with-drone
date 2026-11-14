import { useState, useEffect } from 'react';
import { apiFetch } from '@/shared/lib/api';

interface StreamData {
  streamUrl: string;
  expiresAt: string;
  watermarkSuffix: string;
}

export function useReelStream(token: string) {
  const [data, setData] = useState<StreamData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      // No token in the route (a malformed deep link): show "unavailable" instead of loading forever.
      setError('Clip unavailable');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiFetch<StreamData>(`/api/stream/${encodeURIComponent(token)}`)
      .then((stream) => { if (!cancelled) setData(stream); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Clip unavailable'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token]);

  return { data, loading, error };
}
