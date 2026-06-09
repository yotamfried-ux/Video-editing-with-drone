import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { getSignedStreamUrl } from '@/lib/cloudflare';

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ token: string }> }
) {
  const { token } = await params;

  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('id, stream_uid, status, expires_at, token')
    .eq('token', token)
    .single();

  if (!reel) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (reel.status === 'expired' || new Date(reel.expires_at) < new Date()) {
    return NextResponse.json({ error: 'Expired' }, { status: 410 });
  }

  // Mark as viewed on first watch
  if (reel.status === 'published') {
    await supabaseAdmin.from('reels').update({ status: 'viewed' }).eq('id', reel.id);
    await supabaseAdmin.from('analytics_events').insert({
      event_type: 'reel_viewed',
      reel_id: reel.id,
    });
  }

  const streamUrl = getSignedStreamUrl(reel.stream_uid, 3600);
  const watermarkSuffix = (reel.token as string).slice(-4).toUpperCase();

  return NextResponse.json({ streamUrl, expiresAt: reel.expires_at, watermarkSuffix });
}
