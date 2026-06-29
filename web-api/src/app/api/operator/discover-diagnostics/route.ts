import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';

export const dynamic = 'force-dynamic';

const DISCOVER_STATUSES = ['published', 'viewed', 'sold'];

type ReelRow = {
  id: string;
  token: string | null;
  sport: string | null;
  recording_date: string | null;
  stream_uid: string | null;
  status: string | null;
  expires_at: string | null;
  created_at: string | null;
  source_video?: string | null;
  storage_path?: string | null;
};

function groupSessions(reels: ReelRow[]) {
  const grouped = new Map<string, { recording_date: string | null; sport: string; reels: ReelRow[] }>();
  for (const reel of reels) {
    const key = `${reel.recording_date ?? 'unknown'}__${reel.sport ?? ''}`;
    if (!grouped.has(key)) {
      grouped.set(key, { recording_date: reel.recording_date, sport: reel.sport ?? '', reels: [] });
    }
    grouped.get(key)!.reels.push(reel);
  }
  return [...grouped.values()];
}

export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const limited = await enforceRateLimit(req, 'discover-diagnostics', 60, 60);
  if (limited) return limited;

  const { data, error } = await supabaseAdmin
    .from('reels')
    .select('id, token, sport, recording_date, stream_uid, status, expires_at, created_at, source_video, storage_path')
    .in('status', DISCOVER_STATUSES)
    .order('recording_date', { ascending: false })
    .order('created_at', { ascending: false })
    .limit(20)
    .returns<ReelRow[]>();

  if (error) {
    console.error('discover diagnostics failed', error.message);
    return NextResponse.json({ error: 'Could not load Discover diagnostics' }, { status: 500 });
  }

  return NextResponse.json({
    ok: true,
    eligibleStatuses: DISCOVER_STATUSES,
    reelCount: data?.length ?? 0,
    sessions: groupSessions(data ?? []),
    reels: data ?? [],
  });
}
