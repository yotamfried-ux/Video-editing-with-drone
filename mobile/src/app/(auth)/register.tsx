import React, { useEffect } from 'react';
import { View, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { FormField } from '@/shared/components/FormField';
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
            <Text variant="body" color={Colors.textSecondary} style={{ textAlign: 'center' }}>Step 1 of 2 · your sign-in details</Text>
            <Spacer size={Spacing.xl} />
            <FormField
              testID="register-email"
              label="Email"
              value={reg.email}
              onChangeText={reg.setEmail}
              keyboardType="email-address"
              autoComplete="email"
              returnKeyType="next"
            />
            <FormField
              testID="register-password"
              label="Password"
              hint="At least 6 characters"
              value={reg.password}
              onChangeText={reg.setPassword}
              secure
              autoComplete="new-password"
              returnKeyType="go"
              onSubmitEditing={reg.submitCredentials}
              error={reg.error}
            />
            <Spacer size={Spacing.md} />
            <Button testID="register-continue" label="Continue" onPress={reg.submitCredentials} loading={reg.loading} />
            <Text variant="caption" color={Colors.textSecondary} style={{ textAlign: 'center' }}>
              By continuing you agree to our{' '}
              <Text testID="register-terms" variant="caption" color={Colors.accent} onPress={() => router.push('/legal/terms')}>
                Terms of Service
              </Text>{' '}
              and{' '}
              <Text testID="register-privacy" variant="caption" color={Colors.accent} onPress={() => router.push('/legal/privacy')}>
                Privacy Policy
              </Text>
              .
            </Text>
            <Button
              testID="register-have-account"
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
            <Text variant="body" color={Colors.textSecondary} style={{ textAlign: 'center' }}>Step 2 of 2 · shown on your profile</Text>
            <Spacer size={Spacing.xl} />
            <FormField
              testID="register-name"
              label="Full name"
              value={reg.name}
              onChangeText={reg.setName}
              autoCapitalize="words"
              autoComplete="name"
              returnKeyType="done"
              onSubmitEditing={reg.submitProfile}
              error={reg.error}
            />
            <Spacer size={Spacing.md} />
            <Button testID="register-finish" label="Finish" onPress={reg.submitProfile} loading={reg.loading} />
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
});
