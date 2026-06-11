import { NextRequest, NextResponse } from 'next/server';
import { enforceRateLimit } from '@/lib/ratelimit';

// POST /api/crash — mobile crash report sink.
//
// The app's native + JS crash handlers POST stack traces here. The report is
// written to the function log (visible in Vercel runtime logs) so crashes on
// real devices can be diagnosed without adb or a third-party crash service.
// No auth: a crashing app has no session; rate-limited instead.
export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'crash', 20, 60);
  if (limited) return limited;

  const report = (await req.text()).slice(0, 20_000);
  if (!report.trim()) {
    return NextResponse.json({ error: 'Empty report' }, { status: 400 });
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
