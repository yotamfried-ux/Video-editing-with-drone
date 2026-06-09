import React, { useEffect, useState } from 'react';
import { View, StyleSheet } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Colors, Spacing } from '@/shared/constants/theme';

interface Props {
  children: React.ReactNode;
}

export function OperatorGate({ children }: Props) {
  const [authenticated, setAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authenticate = async () => {
    setError(null);
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Operator access requires biometric authentication',
      fallbackLabel: 'Use Passcode',
    });
    if (result.success) {
      setAuthenticated(true);
    } else {
      setError('Authentication failed. Try again.');
    }
  };

  useEffect(() => {
    authenticate();
  }, []);

  if (authenticated) return <>{children}</>;

  return (
    <View style={styles.container}>
      <Text variant="headline" style={{ textAlign: 'center' }}>
        Operator Access
      </Text>
      <Text
        variant="body"
        color={Colors.textSecondary}
        style={styles.sub}
      >
        Biometric authentication required
      </Text>
      {error && (
        <Text variant="caption" color={Colors.danger}>
          {error}
        </Text>
      )}
      <Button label="Authenticate" onPress={authenticate} />
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
