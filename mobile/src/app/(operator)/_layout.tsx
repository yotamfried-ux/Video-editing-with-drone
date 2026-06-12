import { Redirect, Stack } from 'expo-router';
import { useOperatorUnlock } from '@/features/operator/hooks/useOperatorUnlock';

export default function OperatorLayout() {
  const unlocked = useOperatorUnlock((s) => s.unlocked);
  // Biometric runs at the entry point (profile 5-tap → unlock()). Anyone who
  // lands here without passing it — deep link, stale navigation — is bounced.
  if (!unlocked) return <Redirect href="/(tabs)/profile" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
