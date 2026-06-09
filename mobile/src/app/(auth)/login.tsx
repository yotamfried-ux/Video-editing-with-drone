import React, { useState } from 'react';
import {
  View,
  TextInput,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
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
    const { error: e } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (e) setError(e.message);
    else router.replace('/(tabs)/discover');
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
        <TextInput
          placeholder="Email"
          placeholderTextColor={Colors.textSecondary}
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoCapitalize="none"
          style={styles.input}
        />
        <TextInput
          placeholder="Password"
          placeholderTextColor={Colors.textSecondary}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          style={styles.input}
        />
        {error && (
          <Text variant="caption" color={Colors.danger}>
            {error}
          </Text>
        )}
        <Spacer size={Spacing.md} />
        <Button label="Sign In" onPress={login} loading={loading} />
        <Spacer size={Spacing.sm} />
        <Button
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
  input: {
    backgroundColor: Colors.card,
    color: Colors.textPrimary,
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: '#2D3F55',
    fontSize: 15,
  },
});
