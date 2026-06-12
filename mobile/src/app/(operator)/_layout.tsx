import { Stack, usePathname } from 'expo-router';
import { OperatorGate } from '@/features/operator/components/OperatorGate';

export default function OperatorLayout() {
  const pathname = usePathname();
  // Settings handles its own biometric auth internally so it can be reached
  // before a secret is configured (chicken-and-egg: you need settings to set
  // the secret, but the gate requires a secret to enter settings).
  if (pathname.endsWith('/settings')) {
    return <Stack screenOptions={{ headerShown: false }} />;
  }
  return (
    <OperatorGate>
      <Stack screenOptions={{ headerShown: false }} />
    </OperatorGate>
  );
}
