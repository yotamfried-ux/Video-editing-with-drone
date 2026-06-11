import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';

// POST /api/operator/reprocess — operator sends a reel back for re-editing.
//
// Body: { reel_id?: string, draft_name?: string, notes: string }
// Either reel_id (published reel — draft name resolved from reels.source_video)
// or draft_name (draft still in Drive REVIEW) must be provided.
//
// Inserts a reprocess_requests row; the pipeline consumes it at its next run:
// re-queues the raw source video(s) and injects the notes into the Gemini
// analysis prompt so the operator's feedback directly shapes the re-edit.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  let body: { reel_id?: string; draft_name?: string; notes?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const notes = (body.notes ?? '').trim().slice(0, 2000);
  let draftName = (body.draft_name ?? '').trim();
  const reelId = (body.reel_id ?? '').trim();

  if (!draftName && reelId) {
    const { data: reel, error } = await supabaseAdmin
      .from('reels')
      .select('source_video')
      .eq('id', reelId)
      .single();
    if (error || !reel) {
      return NextResponse.json({ error: 'Reel not found' }, { status: 404 });
    }
    draftName = reel.source_video ?? '';
  }

  if (!draftName) {
    return NextResponse.json(
      { error: 'reel_id or draft_name required' },
      { status: 400 },
    );
  }

  const { data, error } = await supabaseAdmin
    .from('reprocess_requests')
    .insert({ reel_id: reelId || null, draft_name: draftName, notes })
    .select('id')
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, request_id: data.id });
}
