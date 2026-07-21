import React, { useEffect } from 'react';
import { View, TextInput, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { useRegistration } from '@/features/auth/hooks/useRegistration';
import { Colors, Spacing } from '@/shared/constants/theme';

const STEPS = ['Account', 'Profile'] as const;

export default function RegisterScreen() {
  const router = useRouter();
  const { step: stepParam } = useLocalSearchParams<{ step?: string }>();
  const reg = useRegistration(stepParam === 'profile' ? 'profile' : 'credentials');

  useEffect(() => {
    if (reg.step === 'done') router.replace('/(tabs)/discover');
  }, [reg.step, router]);

  const stepIndex = reg.step === 'credentials' ? 0 : 1;

  return (
    <SafeArea>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <View style={styles.dots}>
          {STEPS.map((_, i) => (
            <View
              key={i}
              style={[
                styles.dot,
                i === stepIndex && styles.dotActive,
                i < stepIndex && styles.dotDone,
              ]}
            />
          ))}
        </View>

        {reg.step === 'credentials' && (
          <View style={styles.form}>
            <Text variant="display" style={{ textAlign: 'center' }}>Create Account</Text>
            <Spacer size={Spacing.xl} />
            <TextInput
              placeholder="Email"
              placeholderTextColor={Colors.textSecondary}
              value={reg.email}
              onChangeText={reg.setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              style={styles.input}
            />
            <TextInput
              placeholder="Password (min 6 chars)"
              placeholderTextColor={Colors.textSecondary}
              value={reg.password}
              onChangeText={reg.setPassword}
              secureTextEntry
              style={styles.input}
            />
            {reg.error && <Text variant="caption" color={Colors.danger}>{reg.error}</Text>}
            <Spacer size={Spacing.md} />
            <Button label="Continue" onPress={reg.submitCredentials} loading={reg.loading} />
            <Button
              label="Already have an account?"
              onPress={() => router.push('/(auth)/login')}
              variant="ghost"
              style={{ marginTop: Spacing.sm }}
            />
          </View>
        )}

        {reg.step === 'profile' && (
          <View style={styles.form}>
            <Text variant="display" style={{ textAlign: 'center' }}>Your Name</Text>
            <Spacer size={Spacing.xl} />
            <TextInput
              placeholder="Full name"
              placeholderTextColor={Colors.textSecondary}
              value={reg.name}
              onChangeText={reg.setName}
              style={styles.input}
            />
            {reg.error && <Text variant="caption" color={Colors.danger}>{reg.error}</Text>}
            <Spacer size={Spacing.md} />
            <Button label="Finish" onPress={reg.submitProfile} loading={reg.loading} />
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 8, paddingTop: Spacing.lg },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#1E293B' },
  dotActive: { backgroundColor: '#00E5FF', width: 24 },
  dotDone: { backgroundColor: '#22C55E' },
  form: { flex: 1, padding: Spacing.xl, justifyContent: 'center', gap: Spacing.sm },
  input: {
    backgroundColor: '#1E293B',
    color: '#FFFFFF',
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: '#2D3F55',
    fontSize: 15,
  },
});
