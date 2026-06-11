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

  // Log the exception type on its own line first — Vercel truncates long messages,
  // so the most critical information must come first.
  const lines = report.split('\n').filter((l) => l.trim());
  // Prefer the specific Java exception class (e.g. "java.lang.RuntimeException: ...")
  // over the generic "ANDROID NATIVE CRASH" header so the actual error is visible
  // even in truncated log views.
  const javaLine = lines.find((l) =>
    /^(java|android|com\.facebook|com\.sportreel|expo)\.\S/.test(l.trim())
  );
  const excLine = (javaLine ?? lines.find((l) => /Exception|Error:|CRASH/.test(l)) ?? lines[0] ?? '(empty)').slice(0, 200);
  console.error(`[MOBILE-CRASH] ${new Date().toISOString()} | ${excLine}`);
  // Log remaining stack frames in small batches so each is visible in the log table.
  for (let i = 0; i < lines.length; i += 15) {
    const chunk = lines.slice(i, i + 15).join('\n');
    if (chunk.trim()) console.error(`[CRASH+${i}]\n${chunk}`);
  }

  return NextResponse.json({ ok: true });
}
