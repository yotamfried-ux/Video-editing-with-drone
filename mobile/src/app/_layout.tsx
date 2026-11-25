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
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { PaperProvider } from 'react-native-paper';
import { paperTheme } from '@/shared/constants/paperTheme';
import { supabase } from '@/shared/lib/supabase';
import { useAuthStore } from '@/shared/hooks/useAuth';
import { setCrashContext, installJsCrashReporter } from '@/shared/lib/crashReporter';
import { initSplashScreen, hideSplashScreen } from '@/shared/lib/splash';
import { applyPendingUpdate } from '@/shared/lib/updates';
import { NotificationLinks, syncPushToken } from '@/shared/lib/notificationSetup';
import { ConfirmDialogHost } from '@/shared/lib/alert';

initSplashScreen();
installJsCrashReporter();
void applyPendingUpdate();

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
      if (session) syncPushToken(session.user.id).catch(() => {});
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_, session) => {
      setSession(session);
      if (session) syncPushToken(session.user.id).catch(() => {});
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (fontsLoaded) hideSplashScreen();
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <PaperProvider theme={paperTheme}>
          <CrashContextSync />
          <NotificationLinks />
          <ConfirmDialogHost />
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: paperTheme.colors.background } }} />
        </PaperProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
