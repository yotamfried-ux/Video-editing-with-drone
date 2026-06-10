import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';

// GET /api/operator/reels — operator-only full reel list (all statuses,
// including expired, with athlete_desc). The reels RLS policy no longer
// grants broad anon read, so the operator screen reads through this route.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { data, error } = await supabaseAdmin
    .from('reels')
    .select('id, token, sport, athlete_desc, status, expires_at, recording_date')
    .order('created_at', { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ reels: data ?? [] });
}
