import { NextRequest, NextResponse } from 'next/server';
import { enforceRateLimit } from '@/lib/ratelimit';

// POST /api/crash — mobile crash report sink.
// Accepts structured JSON (from the JS crash reporter) and plain text (from
// the native Kotlin handler installed by plugins/withCrashReporter.js).
// No auth: a crashing app has no session; rate-limited instead.
export async function POST(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'crash', 20, 60);
  if (limited) return limited;

  const contentType = req.headers.get('content-type') ?? '';

  if (contentType.includes('application/json')) {
    const raw = (await req.text()).slice(0, 50_000);
    if (!raw.trim()) return NextResponse.json({ error: 'Empty report' }, { status: 400 });

    try {
      const r = JSON.parse(raw);
      const ts = r.timestamp ?? new Date().toISOString();
      const msg = r.error?.message?.slice(0, 150) ?? '(no message)';
      console.error(`[MOBILE-CRASH] ${ts} | ${r.type} | ${msg}`);
      console.error(
        `[CRASH-DEVICE] platform=${r.device?.platform} os=${r.device?.osVersion} ` +
        `app=${r.device?.appVersion} build=${r.device?.buildNumber}`
      );
      console.error(
        `[CRASH-CONTEXT] user=${r.user?.userId ?? 'anon'} screen=${r.screen?.screen ?? '?'} ` +
        `action=${r.action?.action ?? '?'} network=${r.appState?.network ?? '?'} ` +
        `appState=${r.appState?.reactNativeAppState ?? '?'}`
      );
      if (r.error?.stack) {
        const lines: string[] = r.error.stack.split('\n');
        for (let i = 0; i < lines.length; i += 15) {
          const chunk = lines.slice(i, i + 15).join('\n');
          if (chunk.trim()) console.error(`[CRASH-STACK+${i}]\n${chunk}`);
        }
      }
    } catch {
      console.error(`[MOBILE-CRASH] ${new Date().toISOString()} | failed to parse JSON report`);
    }

    return NextResponse.json({ ok: true });
  }

  // Plain text — native Kotlin handler or legacy JS reporter
  const report = (await req.text()).slice(0, 20_000);
  if (!report.trim()) return NextResponse.json({ error: 'Empty report' }, { status: 400 });

  const lines = report.split('\n').filter((l) => l.trim());
  const javaLine = lines.find((l) =>
    /^(java|android|com\.facebook|com\.sportreel|expo)\.\S/.test(l.trim())
  );
  const excLine = (
    javaLine ??
    lines.find((l) => /Exception|Error:|CRASH/.test(l)) ??
    lines[0] ??
    '(empty)'
  ).slice(0, 200);
  console.error(`[MOBILE-CRASH] ${new Date().toISOString()} | ${excLine}`);
  for (let i = 0; i < lines.length; i += 15) {
    const chunk = lines.slice(i, i + 15).join('\n');
    if (chunk.trim()) console.error(`[CRASH+${i}]\n${chunk}`);
  }

  return NextResponse.json({ ok: true });
}
