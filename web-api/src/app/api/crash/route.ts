import { NextRequest, NextResponse } from 'next/server';
import { enforceRateLimit } from '@/lib/ratelimit';
import { supabaseAdmin } from '@/lib/supabase-admin';

// POST /api/crash — mobile crash report sink.
//
// The app's native + JS crash handlers POST stack traces here. The report is
// written to the function log (visible in Vercel runtime logs) AND stored in
// the crash_reports table, because Vercel's log table truncates messages —
// the full stack trace is only reliably readable from the database.
// No auth: a crashing app has no session; rate-limited instead.
export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'crash', 20, 60);
  if (limited) return limited;

  const contentType = req.headers.get('content-type') ?? '';
  const report = (await req.text()).slice(0, 20_000);
  if (!report.trim()) {
    return NextResponse.json({ error: 'Empty report' }, { status: 400 });
  }

  // Full report → database (survives truncation, queryable later).
  try {
    await supabaseAdmin.from('crash_reports').insert({
      content_type: contentType.slice(0, 100),
      report,
    });
  } catch {
    // storage failure must not block the log path below
  }

  // Put the exception class FIRST so it's visible in Vercel's truncated log table
  // (the table cuts messages at ~30 chars — a leading timestamp wastes all of them).
  const lines = report.split('\n').filter((l) => l.trim());
  const excLine = (
    lines.find((l) => /^(java|android|com\.|expo)\.\S/.test(l.trim())) ??
    lines.find((l) => /Exception|Error:|CRASH/.test(l)) ??
    lines[0] ??
    '(empty)'
  ).slice(0, 200);

  console.error(`[MOBILE-CRASH] ${excLine}`);
  console.error(`[CRASH-META] ts=${new Date().toISOString()} lines=${lines.length}`);
  for (let i = 0; i < lines.length; i += 15) {
    const chunk = lines.slice(i, i + 15).join('\n');
    if (chunk.trim()) console.error(`[CRASH-STACK+${i}]\n${chunk}`);
  }

  return NextResponse.json({ ok: true });
}
