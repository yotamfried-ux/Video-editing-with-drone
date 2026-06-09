import { useState, useEffect } from 'react';
import { supabase } from '@/shared/lib/supabase';

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
    const load = async () => {
      const now = new Date();
      const todayStart = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate()
      ).toISOString();
      const weekStart = new Date(now.getTime() - 7 * 86400000).toISOString();
      const monthStart = new Date(
        now.getFullYear(),
        now.getMonth(),
        1
      ).toISOString();

      const [todayRes, weekRes, monthRes, reelsRes, funnelRes] =
        await Promise.all([
          supabase
            .from('analytics_events')
            .select('revenue_ils')
            .eq('event_type', 'payment_completed')
            .gte('created_at', todayStart),
          supabase
            .from('analytics_events')
            .select('revenue_ils')
            .eq('event_type', 'payment_completed')
            .gte('created_at', weekStart),
          supabase
            .from('analytics_events')
            .select('revenue_ils')
            .eq('event_type', 'payment_completed')
            .gte('created_at', monthStart),
          supabase.from('reels').select('status'),
          supabase.from('analytics_events').select('event_type'),
        ]);

      const sum = (rows: { revenue_ils: number | null }[]) =>
        rows.reduce((a, r) => a + (r.revenue_ils ?? 0), 0);

      const reels = reelsRes.data ?? [];
      const events = funnelRes.data ?? [];

      setData({
        todayRevenue: sum(todayRes.data ?? []),
        weekRevenue: sum(weekRes.data ?? []),
        monthRevenue: sum(monthRes.data ?? []),
        totalReels: reels.length,
        soldReels: reels.filter((r) => r.status === 'sold').length,
        expiredReels: reels.filter((r) => r.status === 'expired').length,
        funnelViewed: events.filter((e) => e.event_type === 'reel_viewed')
          .length,
        funnelCheckout: events.filter(
          (e) => e.event_type === 'checkout_started'
        ).length,
        funnelPaid: events.filter(
          (e) => e.event_type === 'payment_completed'
        ).length,
      });
    };
    load();
  }, []);

  return data;
}
