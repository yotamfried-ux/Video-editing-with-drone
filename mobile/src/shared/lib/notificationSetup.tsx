import { useEffect } from 'react';
import { Platform } from 'react-native';
import { useRouter } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { registerPushToken } from './notifications';
import { supabase } from './supabase';

export async function syncPushToken(userId: string): Promise<void> {
  const token = await registerPushToken();
  if (!token) return;
  await supabase.from('push_tokens').upsert(
    { user_id: userId, token, platform: Platform.OS, updated_at: new Date().toISOString() },
    { onConflict: 'user_id,platform' }
  );
}

export function NotificationLinks() {
  const router = useRouter();
  useEffect(() => {
    const open = (response: Notifications.NotificationResponse | null) => {
      const data = response?.notification.request.content.data as { screen?: string; token?: string } | undefined;
      if (data?.screen === 'reel' && typeof data.token === 'string' && /^[A-Za-z0-9_-]{8,80}$/.test(data.token)) {
        router.push(`/reel/${data.token}`);
      }
    };
    Notifications.getLastNotificationResponseAsync().then(open).catch(() => {});
    const sub = Notifications.addNotificationResponseReceivedListener(open);
    return () => sub.remove();
  }, [router]);
  return null;
}
