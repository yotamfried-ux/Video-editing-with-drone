import { Redirect, Stack } from 'expo-router';
import { useOperatorUnlock } from '@/features/operator/hooks/useOperatorUnlock';

export default function OperatorLayout() {
  const unlocked = useOperatorUnlock((s) => s.unlocked);
  // UPL-01 validates the real Android upload path, not biometric auth. This
  // compile-time Expo flag is enabled only by the validation workflow.
  const validationBypass = process.env.EXPO_PUBLIC_UPL01_OPERATOR_BYPASS === '1';
  if (!unlocked && !validationBypass) return <Redirect href="/(tabs)/profile" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
