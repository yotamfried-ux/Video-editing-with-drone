import { useState, useEffect } from 'react';
import { operatorFetch } from '../lib/operatorApi';
import type { OperatorAnalyticsSummary } from '@/features/operator/types/contracts';

export function useOperatorAnalytics() {
  const [data, setData] = useState<OperatorAnalyticsSummary | null>(null);

  useEffect(() => {
    operatorFetch<OperatorAnalyticsSummary>('/api/analytics')
      .then(setData)
      .catch(() => setData(null));
  }, []);

  return data;
}
