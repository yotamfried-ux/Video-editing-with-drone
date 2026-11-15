import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { notifyFollowers } from '@/lib/athletes';
import { isUuid } from '@/lib/validate';

/**
 * Operator confirms that two athletes are one person: `from` is folded into `into`.
 * Reels and followers move to `into`; followers of `into` are then told once about the reels that joined
 * and are still for sale. Nothing is merged automatically anywhere else.
 */
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const body = await req.json().catch(() => null);
  const from = body?.from;
  const into = body?.into;
  if (!isUuid(from) || !isUuid(into) || from === into) {
    return NextResponse.json({ error: 'from and into must be two different athlete ids' }, { status: 400 });
  }

  const { data: found } = await supabaseAdmin.from('athletes').select('id').in('id', [from, into]);
  if ((found ?? []).length !== 2) return NextResponse.json({ error: 'Athlete not found' }, { status: 404 });

  const { data: moved, error: reelError } = await supabaseAdmin
    .from('reels')
    .update({ athlete_id: into })
    .eq('athlete_id', from)
    .select('id,status');
  if (reelError) return NextResponse.json({ error: reelError.message }, { status: 500 });

  // Followers of `from` become followers of `into`; someone following both keeps one row.
  const { data: fromFollows } = await supabaseAdmin
    .from('athlete_follows')
    .select('user_id,source_reel_id')
    .eq('athlete_id', from);
  for (const follow of fromFollows ?? []) {
    await supabaseAdmin
      .from('athlete_follows')
      .upsert(
        { user_id: follow.user_id, athlete_id: into, source_reel_id: follow.source_reel_id },
        { onConflict: 'user_id,athlete_id', ignoreDuplicates: true },
      );
  }
  const { error: deleteError } = await supabaseAdmin.from('athletes').delete().eq('id', from);
  if (deleteError) return NextResponse.json({ error: deleteError.message }, { status: 500 });

  let notified = 0;
  for (const reel of moved ?? []) {
    if (reel.status === 'published' || reel.status === 'viewed') {
      notified += await notifyFollowers(into, reel.id);
    }
  }
  return NextResponse.json({ merged: true, reels_moved: (moved ?? []).length, notified });
}
