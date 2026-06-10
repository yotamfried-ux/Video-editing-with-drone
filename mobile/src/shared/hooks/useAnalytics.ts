import { apiFetch } from '../lib/api';

// payment_completed is recorded only by the verified payment webhooks on the
// server — the client may not log it (prevents revenue/funnel tampering).
type EventType = 'reel_viewed' | 'checkout_started' | 'download_completed';

export function useAnalytics() {
  const logEvent = async (
    eventType: EventType,
    meta?: { reel_id?: string; payment_id?: string }
  ) => {
    try {
      // analytics_events is service_role-only; insert via the server route.
      await apiFetch('/api/events', {
        method: 'POST',
        body: JSON.stringify({ event_type: eventType, ...meta }),
      });
    } catch {
      // analytics is best-effort; ignore failures
    }
  };
  return { logEvent };
}
