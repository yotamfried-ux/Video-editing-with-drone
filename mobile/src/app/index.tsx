import { Redirect } from 'expo-router';
import { useAuth } from '@/shared/hooks/useAuth';

export default function Index() {
  const { session, loading } = useAuth();

  // Validation-only entry point for UPL-01. This bypasses login/biometric,
  // which are outside this experiment, while keeping the real operator
  // settings, picker and upload implementation under test.
  if (process.env.EXPO_PUBLIC_UPL01_OPERATOR_BYPASS === '1') {
    return <Redirect href="/(operator)/settings" />;
  }

  // Wait for the root layout to hydrate the session from secure storage,
  // otherwise logged-in users flash through the login screen.
  if (loading) return null;
  return <Redirect href={session ? '/(tabs)/discover' : '/(auth)/login'} />;
}
