import { useState, useEffect, useRef } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface PipelineStatus {
  stage: string;
  progress: number;
  meta: Record<string, unknown>;
  updated_at: string;
}

export function usePipelineStatus() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = async () => {
    const { data } = await supabase
      .from('pipeline_status')
      .select('stage, progress, meta, updated_at')
      .eq('id', 1)
      .single();
    if (data) setStatus(data as PipelineStatus);
  };

  useEffect(() => {
    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return status;
}
