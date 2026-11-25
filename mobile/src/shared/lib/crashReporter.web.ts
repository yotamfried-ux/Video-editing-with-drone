import { API_BASE_URL } from './publicEnv';

export interface CrashContext {
  userId?: string;
  screen?: string;
  lastAction?: string;
  network?: 'online' | 'offline' | 'unknown';
  permissions?: Record<string, boolean>;
}

const ENDPOINT = API_BASE_URL + '/api/crash';
let _context: CrashContext = {};
let _installed = false;

export function setCrashContext(ctx: Partial<CrashContext>): void {
  _context = { ..._context, ...ctx };
}

export function logCrashAction(action: string): void {
  _context = { ..._context, lastAction: action };
}

function sendReport(error: unknown, isFatal: boolean): void {
  if (typeof window === 'undefined' || typeof fetch !== 'function') return;
  const e = error as { message?: string; stack?: string };
  const payload = {
    type: isFatal ? 'js-fatal' : 'js-error',
    device: {
      platform: 'web',
      osVersion: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 120) : 'web',
      appVersion: '1.0.0',
      buildNumber: 'web',
    },
    user: { userId: _context.userId },
    screen: { screen: _context.screen },
    action: { action: _context.lastAction },
    error: {
      message: e?.message ?? String(error),
      stack: e?.stack ?? '',
    },
    timestamp: new Date().toISOString(),
  };
  fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

export function reportJsError(error: unknown, isFatal = false): void {
  sendReport(error, isFatal);
}

export function installJsCrashReporter(): void {
  if (_installed || typeof window === 'undefined') return;
  _installed = true;
  window.addEventListener('error', (ev) => {
    sendReport(ev.error ?? ev.message, true);
  });
  window.addEventListener('unhandledrejection', (ev) => {
    sendReport(ev.reason, false);
  });
}
