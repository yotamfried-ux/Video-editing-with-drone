import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { FormField } from '@/shared/components/FormField';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function ForgotPasswordScreen() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestReset = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await supabase.auth.resetPasswordForEmail(normalizedEmail, {
        redirectTo: 'sportreel://reset-password',
      });
      if (result.error) throw result.error;
      // Do not disclose whether this address is registered.
      setSent(true);
    } catch {
      setError('Could not send a reset link right now. Please try again later.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeArea>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <Text variant="display">Reset password</Text>
        <Text variant="body" color={Colors.textSecondary}>
          {sent
            ? 'If an account exists for that address, a password reset link has been sent. Check your inbox and spam folder.'
            : 'Enter your account email and we will send you a secure password reset link.'}
        </Text>
        {!sent ? (
          <>
            <FormField
              testID="forgot-password-email"
              label="Email"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoComplete="email"
              returnKeyType="go"
              onSubmitEditing={requestReset}
              error={error}
            />
            <Button
              testID="forgot-password-submit"
              label="Send reset link"
              onPress={requestReset}
              loading={busy}
              disabled={!email.trim()}
            />
          </>
        ) : null}
        <Button
          testID="forgot-password-back"
          label="Back to sign in"
          variant="ghost"
          onPress={() => router.replace('/(auth)/login')}
        />
      </KeyboardAvoidingView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: Spacing.xl, gap: Spacing.md },
});
