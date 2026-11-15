import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { userIdFromRequest } from '@/lib/user-auth';

const PUBLIC_TOKEN_RE = /^[A-Za-z0-9_-]{8,80}$/;

/**
 * What the signed-in user owns of a reel: whether they bought it, a short-lived link to the clean full
 * reel when they did, and whether they follow its athlete.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const limited = await enforceRateLimit(req, 'reel-ownership', 60, 60);
  if (limited) return limited;

  const { token } = await params;
  if (!PUBLIC_TOKEN_RE.test(token)) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const userId = await userIdFromRequest(req);
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('id, status, full_storage_path, athlete_id')
    .eq('token', token)
    .maybeSingle();
  if (!reel) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const { data: purchase } = await supabaseAdmin
    .from('purchases')
    .select('id')
    .eq('reel_id', reel.id)
    .eq('user_id', userId)
    .eq('status', 'paid')
    .limit(1)
    .maybeSingle();
  const purchased = Boolean(purchase);

  let downloadUrl: string | null = null;
  if (purchased && reel.full_storage_path) {
    const { data: signed } = await supabaseAdmin.storage
      .from('reels')
      .createSignedUrl(reel.full_storage_path, 900);
    downloadUrl = signed?.signedUrl ?? null;
  }

  let following = false;
  if (reel.athlete_id) {
    const { data: follow } = await supabaseAdmin
      .from('athlete_follows')
      .select('id')
      .eq('user_id', userId)
      .eq('athlete_id', reel.athlete_id)
      .maybeSingle();
    following = Boolean(follow);
  }

  return NextResponse.json({
    purchased,
    download_url: downloadUrl,
    can_follow: purchased && Boolean(reel.athlete_id),
    following,
  });
}
