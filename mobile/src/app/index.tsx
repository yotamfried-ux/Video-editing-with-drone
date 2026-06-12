import { Redirect } from 'expo-router';
import { useAuth } from '@/shared/hooks/useAuth';

export default function Index() {
  const { session, loading } = useAuth();
  // Wait for the root layout to hydrate the session from secure storage,
  // otherwise logged-in users flash through the login screen.
  if (loading) return null;
  return <Redirect href={session ? '/(tabs)/discover' : '/(auth)/login'} />;
}
