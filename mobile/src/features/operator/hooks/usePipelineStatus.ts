import { useState, useEffect, useRef } from 'react';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type { PipelineRun, PipelineStatus, PipelineStatusResponse } from '@/features/operator/types/contracts';

export function usePipelineStatus() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [latestRun, setLatestRun] = useState<PipelineRun | null>(null);
  const [globalLiveStale, setGlobalLiveStale] = useState(false);
  const [globalLiveStaleReason, setGlobalLiveStaleReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = async () => {
    try {
      const result = await operatorFetch<PipelineStatusResponse>('/api/operator/pipeline/status');
      setStatus(result.status);
      setLatestRun(result.latest_run ?? null);
      setGlobalLiveStale(Boolean(result.global_live_stale));
      setGlobalLiveStaleReason(result.global_live_stale_reason ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load pipeline status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return { status, latestRun, globalLiveStale, globalLiveStaleReason, loading, error };
}
