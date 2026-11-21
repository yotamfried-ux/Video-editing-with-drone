import React, { useCallback, useEffect, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { FormField } from '@/shared/components/FormField';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

function recoveryParams(rawUrl: string): URLSearchParams | null {
  try {
    const url = new URL(rawUrl);
    const route = `${url.hostname}${url.pathname}`.replace(/^\/+|\/+$/g, '');
    if (url.protocol !== 'sportreel:' || route !== 'reset-password') return null;
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const query = url.searchParams;
    return fragment.has('access_token') || fragment.has('error')
      ? fragment
      : query;
  } catch {
    return null;
  }
}

export default function ResetPasswordScreen() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);

  const processLink = useCallback(async (url: string | null) => {
    if (!url) return;
    const params = recoveryParams(url);
    if (!params) return;
    setReady(false);
    if (params.has('error')) {
      setError('This reset link is invalid or expired. Request another link.');
      return;
    }
    try {
      const access = params.get('access_token');
      const refresh = params.get('refresh_token');
      const code = params.get('code');
      // Never accept a normal sign-in or email-confirmation URL as password recovery.
      if (access && refresh && params.get('type') === 'recovery') {
        const { error: e } = await supabase.auth.setSession({
          access_token: access,
          refresh_token: refresh,
        });
        if (e) throw e;
      } else if (code) {
        const { error: e } = await supabase.auth.exchangeCodeForSession(code);
        if (e) throw e;
      } else {
        throw new Error('Missing recovery credentials');
      }
      setError(null);
      setReady(true);
    } catch {
      setError('This reset link is invalid or expired. Request another link.');
    }
  }, []);

  useEffect(() => {
    Linking.getInitialURL().then(processLink).catch(() => {
      setError('Could not read the reset link.');
    });
    const subscription = Linking.addEventListener('url', (event) => {
      void processLink(event.url);
    });
    const { data: { subscription: authSubscription } } = supabase.auth.onAuthStateChange(
      (event) => {
        if (event === 'PASSWORD_RECOVERY') setReady(true);
      }
    );
    return () => {
      subscription.remove();
      authSubscription.unsubscribe();
    };
  }, [processLink]);

  const changePassword = async () => {
    if (!ready || busy) return;
    if (password.length < 8) {
      setError('Use at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { error: e } = await supabase.auth.updateUser({ password });
      if (e) throw e;
      await supabase.auth.signOut({ scope: 'local' });
      router.replace('/(auth)/login');
    } catch {
      setError('Could not update the password. Request a new reset link if it expired.');
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
        <Text variant="display">Choose a new password</Text>
        {!ready ? (
          <Text variant="body" color={Colors.textSecondary}>
            {error ?? 'Open this screen from the secure link in your password reset email.'}
          </Text>
        ) : (
          <>
            <FormField
              testID="reset-password-new"
              label="New password"
              value={password}
              onChangeText={setPassword}
              secure
              autoComplete="new-password"
            />
            <FormField
              testID="reset-password-confirm"
              label="Confirm password"
              value={confirm}
              onChangeText={setConfirm}
              secure
              autoComplete="new-password"
              error={error}
            />
            <Button
              testID="reset-password-submit"
              label="Update password"
              onPress={changePassword}
              loading={busy}
              disabled={!password || !confirm}
            />
          </>
        )}
        <Button
          testID="reset-password-back"
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
