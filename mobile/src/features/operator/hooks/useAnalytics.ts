import { useState, useEffect } from 'react';
import { operatorFetch } from '../lib/operatorApi';

interface AnalyticsSummary {
  todayRevenue: number;
  weekRevenue: number;
  monthRevenue: number;
  totalReels: number;
  soldReels: number;
  expiredReels: number;
  funnelViewed: number;
  funnelCheckout: number;
  funnelPaid: number;
}

export function useOperatorAnalytics() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);

  useEffect(() => {
    // analytics_events is service_role-only; the summary is computed server-side
    // and fetched here behind the operator secret (web-api /api/analytics).
    operatorFetch<AnalyticsSummary>('/api/analytics')
      .then(setData)
      .catch(() => setData(null));
  }, []);

  return data;
}
