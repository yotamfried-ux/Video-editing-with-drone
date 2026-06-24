import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const page = parseInt(searchParams.get('page') ?? '1');
  const limit = Math.min(parseInt(searchParams.get('limit') ?? '20'), 50);
  const sport = searchParams.get('sport');
  const offset = (page - 1) * limit;

  let query = supabaseAdmin
    .from('reels')
    .select('id, token, sport, recording_date, stream_uid, status, expires_at, created_at')
    .in('status', ['published', 'viewed', 'sold'])
    .order('recording_date', { ascending: false })
    .order('created_at', { ascending: false })
    .range(offset, offset + limit - 1);

  if (sport) query = query.eq('sport', sport);

  const { data: reels, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Group by date + sport
  const grouped = new Map<string, { recording_date: string; sport: string; reels: typeof reels }>();
  for (const reel of reels ?? []) {
    const key = `${reel.recording_date}__${reel.sport}`;
    if (!grouped.has(key)) {
      grouped.set(key, { recording_date: reel.recording_date, sport: reel.sport ?? '', reels: [] });
    }
    grouped.get(key)!.reels.push(reel);
  }

  // hasMore is based on raw reel count — sessions are grouped, so their
  // length says nothing about whether another page of reels exists.
  return NextResponse.json({
    sessions: [...grouped.values()],
    hasMore: (reels?.length ?? 0) === limit,
  });
}
