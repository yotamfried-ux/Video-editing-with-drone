import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

// Client-loggable event types. `payment_completed` is intentionally excluded —
// only the verified payment webhooks may record revenue, so a client can never
// inflate the funnel or revenue numbers.
const ALLOWED = new Set(['reel_viewed', 'checkout_started', 'download_completed']);

// POST /api/events — server-side analytics logging.
//
// analytics_events is service_role-only by RLS, so the mobile client cannot
// insert directly. This route accepts a constrained event from the app and
// writes it with the service role.
export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'events', 60, 60);
  if (limited) return limited;

  const { event_type, reel_id, payment_id } = await req.json();

  if (typeof event_type !== 'string' || !ALLOWED.has(event_type)) {
    return NextResponse.json({ error: 'Invalid event_type' }, { status: 400 });
  }
  if (reel_id !== undefined && !isUuid(reel_id)) {
    return NextResponse.json({ error: 'Invalid reel_id' }, { status: 400 });
  }
  if (payment_id !== undefined && !isUuid(payment_id)) {
    return NextResponse.json({ error: 'Invalid payment_id' }, { status: 400 });
  }

  await supabaseAdmin.from('analytics_events').insert({
    event_type,
    ...(reel_id ? { reel_id } : {}),
    ...(payment_id ? { payment_id } : {}),
  });

  return NextResponse.json({ ok: true });
}
