/**
 * JS-level crash reporter — companion to the native handler installed by
 * plugins/withCrashReporter.js. Catches fatal JS errors (which on release
 * builds also kill the app) and POSTs them to the web-api crash sink.
 */
const ENDPOINT =
  (process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://video-editing-with-drone.vercel.app') +
  '/api/crash';

export function installJsCrashReporter(): void {
  const errorUtils = (global as any).ErrorUtils;
  if (!errorUtils?.setGlobalHandler) return;

  const previous = errorUtils.getGlobalHandler?.();
  errorUtils.setGlobalHandler((error: unknown, isFatal?: boolean) => {
    try {
      const e = error as { message?: string; stack?: string };
      // fire-and-forget — never block or throw inside the crash path
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: `JS ${isFatal ? 'FATAL' : 'ERROR'}\n${e?.message ?? String(error)}\n${e?.stack ?? ''}`,
      }).catch(() => {});
    } catch {
      // reporting must never make things worse
    }
    previous?.(error, isFatal);
  });
}
