import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';

const PUBLIC_TOKEN_RE = /^[A-Za-z0-9_-]{8,80}$/;

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> }
) {
  const limited = await enforceRateLimit(req, 'stream', 30, 60);
  if (limited) return limited;

  const { token } = await params;
  if (!PUBLIC_TOKEN_RE.test(token)) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('id, storage_path, status, expires_at, token')
    .eq('token', token)
    .single();

  if (!reel) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (reel.status === 'expired' || new Date(reel.expires_at) < new Date()) {
    return NextResponse.json({ error: 'Expired' }, { status: 410 });
  }
  if (!reel.storage_path) {
    return NextResponse.json({ error: 'File not available' }, { status: 404 });
  }

  if (reel.status === 'published') {
    await supabaseAdmin.from('reels').update({ status: 'viewed' }).eq('id', reel.id);
    await supabaseAdmin.from('analytics_events').insert({
      event_type: 'reel_viewed',
      reel_id: reel.id,
    });
  }

  const { data: signed } = await supabaseAdmin.storage
    .from('reels')
    .createSignedUrl(reel.storage_path, 900);

  if (!signed?.signedUrl) {
    return NextResponse.json({ error: 'Could not generate preview URL' }, { status: 500 });
  }

  const watermarkSuffix = (reel.token as string).slice(-4).toUpperCase();

  return NextResponse.json({
    streamUrl: signed.signedUrl,
    expiresAt: reel.expires_at,
    watermarkSuffix,
  });
}
