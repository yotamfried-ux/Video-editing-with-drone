import React, { useState } from 'react';
import {
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { FormField } from '@/shared/components/FormField';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function LoginScreen() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = async () => {
    setLoading(true);
    setError(null);
    const { data, error: e } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (e) {
      setError(e.message);
      setLoading(false);
      return;
    }
    // Resume onboarding if the profile was never completed (e.g. the user
    // signed up but closed the app before entering their name).
    const { data: profile } = await supabase
      .from('athlete_profiles')
      .select('name')
      .eq('user_id', data.user.id)
      .maybeSingle();
    router.replace(
      profile?.name ? '/(tabs)/discover' : '/(auth)/register?step=profile&nameOnly=true'
    );
    setLoading(false);
  };

  return (
    <SafeArea>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <Text variant="display" style={{ textAlign: 'center' }}>
          Welcome Back
        </Text>
        <Text
          variant="body"
          color={Colors.textSecondary}
          style={{ textAlign: 'center' }}
        >
          Sign in to view your highlights
        </Text>
        <Spacer size={Spacing.xl} />
        <FormField
          testID="login-email"
          label="Email"
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoComplete="email"
          returnKeyType="next"
        />
        <FormField
          testID="login-password"
          label="Password"
          value={password}
          onChangeText={setPassword}
          secure
          autoComplete="password"
          returnKeyType="go"
          onSubmitEditing={login}
          error={error}
        />
        <Spacer size={Spacing.md} />
        <Button testID="login-submit" label="Sign In" onPress={login} loading={loading} disabled={!email.trim() || !password} />
        <Spacer size={Spacing.sm} />
        <Button
          testID="login-forgot-password"
          label="Forgot Password?"
          variant="ghost"
          onPress={() => router.push('/(auth)/forgot-password')}
        />
        <Button
          testID="login-create-account"
          label="Create Account"
          onPress={() => router.push('/(auth)/register')}
          variant="ghost"
        />
      </KeyboardAvoidingView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: Spacing.xl,
    justifyContent: 'center',
    gap: Spacing.sm,
  },
});
