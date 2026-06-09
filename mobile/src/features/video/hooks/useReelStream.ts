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
    if (!token) return;
    apiFetch<StreamData>(`/api/stream/${token}`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token]);

  return { data, loading, error };
}
