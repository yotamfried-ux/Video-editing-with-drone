import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { supabase } from './supabase';

// Module-level handler registration must never crash app startup — on Android
// release builds without google-services.json the native FCM module can throw.
try {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
} catch {
  // Notifications unavailable (e.g. missing Firebase config) — app still works.
}

export async function registerPushToken(): Promise<void> {
  if (Platform.OS === 'web') return;

  try {
    const { status: existing } = await Notifications.getPermissionsAsync();
    let finalStatus = existing;
    if (existing !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }
    if (finalStatus !== 'granted') return;

    // SDK 52 requires an explicit projectId for push tokens.
    const projectId = Constants.expoConfig?.extra?.eas?.projectId;
    const { data: token } = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    );

    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;

    await supabase
      .from('athlete_profiles')
      .update({ push_token: token })
      .eq('user_id', user.id);
  } catch (e) {
    // Push registration is best-effort — never let it break the session flow.
    if (__DEV__) console.warn('Push token registration failed:', e);
  }
}
