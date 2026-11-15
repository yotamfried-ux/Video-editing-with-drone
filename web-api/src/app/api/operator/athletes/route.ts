import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { type AthleteSummary, suggestMerges } from '@/lib/athletes';

/** Athletes on Discover with their reels and followers, plus cross-session "same person?" suggestions. */
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const [{ data: athletes, error }, { data: reels }, { data: follows }] = await Promise.all([
    supabaseAdmin.from('athletes').select('id,label,created_at').order('created_at', { ascending: false }).limit(500),
    supabaseAdmin.from('reels').select('athlete_id,recording_date').not('athlete_id', 'is', null).limit(5000),
    supabaseAdmin.from('athlete_follows').select('athlete_id').limit(5000),
  ]);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const summaries: AthleteSummary[] = (athletes ?? []).map((athlete) => {
    const own = (reels ?? []).filter((reel) => reel.athlete_id === athlete.id);
    return {
      id: athlete.id,
      label: athlete.label ?? '',
      reel_count: own.length,
      recording_dates: [...new Set(own.map((reel) => String(reel.recording_date)))].sort(),
      follower_count: (follows ?? []).filter((follow) => follow.athlete_id === athlete.id).length,
    };
  });

  return NextResponse.json({ athletes: summaries, suggestions: suggestMerges(summaries) });
}
