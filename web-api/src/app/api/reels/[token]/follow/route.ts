import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { userIdFromRequest } from '@/lib/user-auth';

const PUBLIC_TOKEN_RE = /^[A-Za-z0-9_-]{8,80}$/;

type Resolved =
  | { error: NextResponse }
  | { error?: undefined; userId: string; reel: { id: string; athlete_id: string | null } };

async function resolve(req: NextRequest, token: string): Promise<Resolved> {
  if (!PUBLIC_TOKEN_RE.test(token)) return { error: NextResponse.json({ error: 'Not found' }, { status: 404 }) };
  const userId = await userIdFromRequest(req);
  if (!userId) return { error: NextResponse.json({ error: 'Unauthorized' }, { status: 401 }) };
  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('id, athlete_id')
    .eq('token', token)
    .maybeSingle();
  if (!reel) return { error: NextResponse.json({ error: 'Not found' }, { status: 404 }) };
  return { userId, reel };
}

/**
 * "Tell me when this athlete has more clips." Only the buyer of the reel can turn it on: following is tied
 * to a paid purchase by the same signed-in user.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const limited = await enforceRateLimit(req, 'reel-follow', 20, 60);
  if (limited) return limited;
  const { token } = await params;
  const resolved = await resolve(req, token);
  if (resolved.error) return resolved.error;
  const { userId, reel } = resolved;

  if (!reel.athlete_id) {
    return NextResponse.json({ error: 'This clip is not linked to an athlete yet' }, { status: 409 });
  }
  const { data: purchase } = await supabaseAdmin
    .from('purchases')
    .select('id')
    .eq('reel_id', reel.id)
    .eq('user_id', userId)
    .eq('status', 'paid')
    .limit(1)
    .maybeSingle();
  if (!purchase) {
    return NextResponse.json({ error: 'Buy this clip to follow its athlete' }, { status: 403 });
  }

  const { error } = await supabaseAdmin
    .from('athlete_follows')
    .upsert(
      { user_id: userId, athlete_id: reel.athlete_id, source_reel_id: reel.id },
      { onConflict: 'user_id,athlete_id', ignoreDuplicates: true },
    );
  if (error) return NextResponse.json({ error: 'Could not follow' }, { status: 500 });
  return NextResponse.json({ following: true });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const limited = await enforceRateLimit(req, 'reel-follow', 20, 60);
  if (limited) return limited;
  const { token } = await params;
  const resolved = await resolve(req, token);
  if (resolved.error) return resolved.error;
  const { userId, reel } = resolved;
  if (reel.athlete_id) {
    const { error } = await supabaseAdmin
      .from('athlete_follows')
      .delete()
      .eq('user_id', userId)
      .eq('athlete_id', reel.athlete_id);
    if (error) return NextResponse.json({ error: 'Could not unfollow' }, { status: 500 });
  }
  return NextResponse.json({ following: false });
}
