import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';

// GET /api/analytics — operator-only revenue + funnel summary.
//
// analytics_events is locked to service_role by RLS, so the mobile client
// cannot (and must not) read it directly with the anon key. This route runs
// the aggregation server-side behind the operator secret.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
  const weekStart = new Date(now.getTime() - 7 * 86400000).toISOString();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();

  const [todayRes, weekRes, monthRes, reelsRes, funnelRes] = await Promise.all([
    supabaseAdmin
      .from('analytics_events')
      .select('revenue_ils')
      .eq('event_type', 'payment_completed')
      .gte('created_at', todayStart),
    supabaseAdmin
      .from('analytics_events')
      .select('revenue_ils')
      .eq('event_type', 'payment_completed')
      .gte('created_at', weekStart),
    supabaseAdmin
      .from('analytics_events')
      .select('revenue_ils')
      .eq('event_type', 'payment_completed')
      .gte('created_at', monthStart),
    supabaseAdmin.from('reels').select('status'),
    supabaseAdmin.from('analytics_events').select('event_type'),
  ]);

  const sum = (rows: { revenue_ils: number | null }[] | null) =>
    (rows ?? []).reduce((a, r) => a + (r.revenue_ils ?? 0), 0);

  const reels = reelsRes.data ?? [];
  const events = funnelRes.data ?? [];

  return NextResponse.json({
    todayRevenue: sum(todayRes.data),
    weekRevenue: sum(weekRes.data),
    monthRevenue: sum(monthRes.data),
    totalReels: reels.length,
    soldReels: reels.filter((r) => r.status === 'sold').length,
    expiredReels: reels.filter((r) => r.status === 'expired').length,
    funnelViewed: events.filter((e) => e.event_type === 'reel_viewed').length,
    funnelCheckout: events.filter((e) => e.event_type === 'checkout_started').length,
    funnelPaid: events.filter((e) => e.event_type === 'payment_completed').length,
  });
}
