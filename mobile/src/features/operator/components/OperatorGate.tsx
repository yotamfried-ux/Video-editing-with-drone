import React, { useEffect, useState } from 'react';
import { View, StyleSheet } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import { useRouter } from 'expo-router';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Colors, Spacing } from '@/shared/constants/theme';
import { getOperatorSecret } from '../lib/operatorSecret';

interface Props {
  children: React.ReactNode;
}

type State = 'loading' | 'no-secret' | 'awaiting-biometric' | 'authenticated' | 'failed';

export function OperatorGate({ children }: Props) {
  const router = useRouter();
  const [state, setState] = useState<State>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Check secret exists before requesting biometric — if there is no secret
    // this device is not an operator device and there is nothing to protect.
    getOperatorSecret().then((secret) => {
      if (!secret) {
        setState('no-secret');
      } else {
        setState('awaiting-biometric');
        triggerBiometric();
      }
    });
  }, []);

  const triggerBiometric = async () => {
    setError(null);
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Operator access requires biometric authentication',
      fallbackLabel: 'Use Passcode',
    });
    if (result.success) {
      setState('authenticated');
    } else {
      setState('failed');
      setError('Authentication failed. Try again.');
    }
  };

  if (state === 'authenticated') return <>{children}</>;

  if (state === 'no-secret') {
    return (
      <View style={styles.container}>
        <Text variant="headline" style={{ textAlign: 'center' }}>Operator Access</Text>
        <Text variant="body" color={Colors.textSecondary} style={styles.sub}>
          This device has no operator secret configured.
          You cannot use the operator area without it.
        </Text>
        <Button
          label="Set up operator secret"
          onPress={() => {
            // Require biometric even for secret setup
            LocalAuthentication.authenticateAsync({
              promptMessage: 'Confirm your identity to set up operator access',
              fallbackLabel: 'Use Passcode',
            }).then((r) => {
              if (r.success) router.replace('/(operator)/settings');
            });
          }}
        />
        <Button
          label="Go back"
          onPress={() => router.replace('/(tabs)/discover')}
          variant="ghost"
          style={{ marginTop: Spacing.sm }}
        />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text variant="headline" style={{ textAlign: 'center' }}>Operator Access</Text>
      <Text variant="body" color={Colors.textSecondary} style={styles.sub}>
        Biometric authentication required
      </Text>
      {error && (
        <Text variant="caption" color={Colors.danger}>{error}</Text>
      )}
      {state === 'failed' && (
        <Button label="Try again" onPress={triggerBiometric} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    gap: Spacing.md,
  },
  sub: { textAlign: 'center', marginBottom: Spacing.md },
});
