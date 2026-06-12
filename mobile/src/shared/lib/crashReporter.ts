import { Platform, AppState } from 'react-native';
import Constants from 'expo-constants';

export interface CrashContext {
  userId?: string;
  screen?: string;
  lastAction?: string;
  network?: 'online' | 'offline' | 'unknown';
  permissions?: Record<string, boolean>;
}

const ENDPOINT =
  (process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://video-editing-with-drone.vercel.app') +
  '/api/crash';

let _context: CrashContext = {};

export function setCrashContext(ctx: Partial<CrashContext>): void {
  _context = { ..._context, ...ctx };
}

export function logCrashAction(action: string): void {
  _context = { ..._context, lastAction: action };
}

function buildReport(error: unknown, isFatal: boolean) {
  const e = error as { message?: string; stack?: string };
  const cfg = Constants.expoConfig as any;
  return {
    type: isFatal ? 'js-fatal' : 'js-error',
    device: {
      platform: Platform.OS,
      osVersion: String(Platform.Version),
      appVersion: cfg?.version ?? '?',
      buildNumber: String(cfg?.android?.versionCode ?? cfg?.ios?.buildNumber ?? '?'),
    },
    user: { userId: _context.userId },
    screen: { screen: _context.screen },
    action: { action: _context.lastAction },
    error: {
      message: e?.message ?? String(error),
      stack: e?.stack ?? '',
    },
    appState: {
      network: _context.network ?? 'unknown',
      reactNativeAppState: AppState.currentState,
      permissions: _context.permissions,
    },
    timestamp: new Date().toISOString(),
  };
}

export function installJsCrashReporter(): void {
  const errorUtils = (global as any).ErrorUtils;
  if (!errorUtils?.setGlobalHandler) return;

  const previous = errorUtils.getGlobalHandler?.();
  errorUtils.setGlobalHandler((error: unknown, isFatal?: boolean) => {
    try {
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildReport(error, isFatal ?? false)),
      }).catch(() => {});
    } catch {
      // reporting must never make things worse
    }
    previous?.(error, isFatal);
  });
}
