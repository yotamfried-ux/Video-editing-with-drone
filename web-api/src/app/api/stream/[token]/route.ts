import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';

type ReelRow = {
  id: string;
  storage_path: string | null;
  status: string | null;
  expires_at: string;
  token: string;
  preview_duration_sec?: number | null;
  full_duration_sec?: number | null;
};

const PUBLIC_TOKEN_RE = /^[A-Za-z0-9_-]{8,80}$/;

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> }
) {
  const limited = await enforceRateLimit(req, 'stream', 30, 60);
  if (limited) return limited;

  const { token } = await params;
  if (!PUBLIC_TOKEN_RE.test(token)) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  // storage_path is the Discover preview: a short, small, watermarked excerpt. The clean full-length reel
  // (full_storage_path) is never returned here; it is signed only after a verified payment.
  let { data: reel } = await supabaseAdmin
    .from('reels')
    .select('id, storage_path, status, expires_at, token, preview_duration_sec, full_duration_sec')
    .eq('token', token)
    .maybeSingle<ReelRow>();
  if (!reel) {
    // Before the preview/full migration is applied the duration columns do not exist.
    ({ data: reel } = await supabaseAdmin
      .from('reels')
      .select('id, storage_path, status, expires_at, token')
      .eq('token', token)
      .maybeSingle<ReelRow>());
  }

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
    isPreview: true,
    previewSeconds: reel.preview_duration_sec ?? null,
    fullSeconds: reel.full_duration_sec ?? null,
    sold: reel.status === 'sold',
  });
}
