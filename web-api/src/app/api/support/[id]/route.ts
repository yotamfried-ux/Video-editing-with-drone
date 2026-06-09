import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { reply } = await req.json();

  if (!reply?.trim()) {
    return NextResponse.json({ error: 'Reply text required' }, { status: 400 });
  }

  const { data: ticket } = await supabaseAdmin
    .from('support_tickets')
    .update({
      operator_reply: reply,
      status: 'replied',
      replied_at: new Date().toISOString(),
    })
    .eq('id', id)
    .select('user_id, reels(sport)')
    .single();

  if (!ticket) return NextResponse.json({ error: 'Ticket not found' }, { status: 404 });

  // Push notification to athlete
  const { data: profile } = await supabaseAdmin
    .from('athlete_profiles')
    .select('push_token')
    .eq('user_id', ticket.user_id)
    .single();

  if (profile?.push_token) {
    await fetch('https://exp.host/--/api/v2/push/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        to: profile.push_token,
        title: 'Support reply from SportReel',
        body: 'We replied to your support request. Tap to view.',
        data: { screen: 'support' },
      }),
    }).catch(() => {}); // non-critical
  }

  return NextResponse.json({ ok: true });
}
