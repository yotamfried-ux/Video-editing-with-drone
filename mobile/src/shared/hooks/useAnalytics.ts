import { supabase } from '../lib/supabase';

type EventType =
  | 'reel_viewed'
  | 'checkout_started'
  | 'payment_completed'
  | 'download_completed';

export function useAnalytics() {
  const logEvent = async (
    eventType: EventType,
    meta?: { reel_id?: string; payment_id?: string }
  ) => {
    try {
      await supabase.from('analytics_events').insert({
        event_type: eventType,
        ...meta,
      });
    } catch {
      // analytics is best-effort; ignore failures
    }
  };
  return { logEvent };
}
