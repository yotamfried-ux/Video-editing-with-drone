import { Stack } from 'expo-router';
import { OperatorGate } from '@/features/operator/components/OperatorGate';

export default function OperatorLayout() {
  return (
    <OperatorGate>
      <Stack screenOptions={{ headerShown: false }} />
    </OperatorGate>
  );
}
