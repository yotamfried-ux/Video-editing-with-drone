import { useEffect } from 'react';
import { Stack, usePathname } from 'expo-router';
import {
  useFonts,
  PlusJakartaSans_400Regular,
  PlusJakartaSans_500Medium,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_700Bold,
  PlusJakartaSans_800ExtraBold,
} from '@expo-google-fonts/plus-jakarta-sans';
import * as SplashScreen from 'expo-splash-screen';
import * as Updates from 'expo-updates';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { StripeProvider } from '@stripe/stripe-react-native';
import { supabase } from '@/shared/lib/supabase';
import { useAuthStore } from '@/shared/hooks/useAuth';
import { registerPushToken } from '@/shared/lib/notifications';
import { setCrashContext, installJsCrashReporter } from '@/shared/lib/crashReporter';

SplashScreen.preventAutoHideAsync();
installJsCrashReporter();

// Apply pending OTA updates on cold start so fixes land on the first open,
// not the one after. Incompatible bundles are filtered out by the
// fingerprint runtimeVersion, so reloading here is safe.
async function applyPendingUpdate() {
  if (__DEV__ || !Updates.isEnabled) return;
  try {
    const check = await Updates.checkForUpdateAsync();
    if (check.isAvailable) {
      await Updates.fetchUpdateAsync();
      await Updates.reloadAsync();
    }
  } catch {
    // Offline or update server unreachable — continue with the current bundle.
  }
}
applyPendingUpdate();

function CrashContextSync() {
  const pathname = usePathname();
  const userId = useAuthStore((s) => s.user?.id);

  useEffect(() => { setCrashContext({ screen: pathname }); }, [pathname]);
  useEffect(() => { setCrashContext({ userId }); }, [userId]);

  return null;
}

export default function RootLayout() {
  const setSession = useAuthStore((s) => s.setSession);

  const [fontsLoaded] = useFonts({
    PlusJakartaSans_400Regular,
    PlusJakartaSans_500Medium,
    PlusJakartaSans_600SemiBold,
    PlusJakartaSans_700Bold,
    PlusJakartaSans_800ExtraBold,
  });

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      if (session) registerPushToken().catch(() => {});
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_, session) => {
      setSession(session);
      if (session) registerPushToken().catch(() => {});
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hideAsync();
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StripeProvider
          publishableKey={
            process.env.EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? ''
          }
        >
          <CrashContextSync />
          <Stack screenOptions={{ headerShown: false }} />
        </StripeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
