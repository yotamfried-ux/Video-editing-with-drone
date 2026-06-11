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

  // One log line per crash, greppable marker first.
  console.error(`[MOBILE-CRASH] ${new Date().toISOString()}\n${report}`);

  return NextResponse.json({ ok: true });
}
